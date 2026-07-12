"""Cascade de rattachement des personnes aux `source_authorships` : `match` puis `create`.

Deux populations de candidats traversent la même cascade :

- **In-périmètre** (`source_authorships.in_perimeter = TRUE`) : authorships dont la source a détecté une affiliation dans le périmètre. Éligibles à tous les barreaux.
- **Hors-périmètre** ancrés (`in_perimeter = FALSE`) : rattachables sans forme de nom — identifiant fort partagé avec une personne connue, ou ancrage cross-source (même publication × position qu'un authorship déjà lié). Le barreau `person_name_forms` (match unique / création) y est neutralisé : un nom seul ne peut ni introduire ni attacher une personne hors-périmètre.

`match` interroge, pour chaque signature non liée, les signaux du plus fiable au moins fiable et rattache **sans jamais créer** :

1. **ORCID** déposé par l'auteur (`ORCID_MATCH_SOURCES` : crossref / openalex / hal) — l'ORCID WoS, algorithmique, n'est pas un signal.
2. **`hal_person_id`** — compte HAL, porté par les authorships HAL.
3. **IdRef**.
4. **Match par `person_name_forms`** — nom normalisé désignant une seule personne. Avant le cross-source, pour maximiser les ancres fermes que ce dernier exploite.
5. **Cross-source** — même publication × position, nom compatible ; inopérant au bootstrap.

Un match par identifiant est **corroboré par le nom** : refusé (et journalisé) si le nom de la signature est incompatible avec le propriétaire de la valeur (identifiant recopié sur le mauvais co-auteur). Les signatures qu'aucun signal ne rattache — nom inconnu, ou ambigu — restent non liées.

`create` reprend les signatures restées non liées et les re-juge contre l'état ferme désormais complet, **cross-source et forme de nom seulement** (les restantes n'ont aucun match identifiant, sinon `match` les aurait prises). Une à-créer peut ainsi rejoindre par cross-source une ancre d'une autre source de la même publication — deux graphies du même auteur aux formes disjointes (« Jean Martin » / « J-P Martin ») ne créent pas deux personnes selon l'ordre ; ne restent créées que les vraies inconnues. `create` recharge ses index depuis la base : il voit tout ce que `match` a posé, la création reste différée sans liste en mémoire.

Garde de rejet : les personnes rejetées pour la publication (`rejected_authorships`) sont éliminées des candidats à chaque signal — un match ne recrée pas une paire rejetée, et l'élimination peut désambiguïser un name form (2 candidats dont 1 rejeté → match univoque).
"""

import logging
from collections import defaultdict
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.persons.loading import (
    EnrichedAuthorship,
    get_all_unlinked_authorships,
    get_out_of_perimeter_candidates,
    load_linked_authorships_by_pub,
)
from application.pipeline.persons.metrics import CascadeResult
from application.ports.pipeline.persons_create import PersonsCreateQueries
from application.ports.repositories.person_repository import PersonRepository
from application.services.persons.core import (
    add_identifiers_from_authorships as add_identifiers,
    add_name_form,
    create_person,
    link_authorships as link_to_person,
)
from domain.persons.matching import (
    ORCID_MATCH_SOURCES,
    RESOLUTION_MODE_BY_REASON,
    NameFormDecision,
    PersonMatchDecision,
    decide_cross_source_match,
    decide_match_by_identifier,
    decide_name_form_outcome,
    decide_person_match,
)
from domain.persons.name_forms import compute_person_name_forms

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _max_authors_per_pub(
    all_authorships: list[EnrichedAuthorship],
    linked_index: dict[tuple[int, int], list[tuple[int, str, str, str]]],
) -> dict[int, int]:
    """Nombre d'auteurs pour chaque publication (max parmi les sources).

    Sert au court-circuit du matching cross-source au-delà de `MAX_AUTHORS_CROSS_SOURCE`. Le matching personnes "cross-source" repose sur le triplet "même publi récupérée sur plusieurs sources, même position auteur, noms compatibles". Sur les méga-papers, ce triplet cesse d'être discriminant : désalignements de positions fréquents entre sources, homonymes de patronyme, prénoms réduits à l'initiale. Le seuil 50 est un proxy arbitraire pour écarter ces publis.

    Une publi peut avoir un nombre d'auteurs différent selon la source — il faut bien retenir un chiffre pour comparer au seuil. On prend le plus élevé par défensivité : si HAL dit 48 et OpenAlex 52, on est dans le régime méga-paper.
    """
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for a in all_authorships:
        if a.publication_id is None:
            continue
        counts[a.publication_id][a.source] += 1
    for (pub_id, _pos), candidates in linked_index.items():
        for _pid, _ln, _fn, src in candidates:
            counts[pub_id][src] += 1
    return {pub_id: max(per_source.values()) for pub_id, per_source in counts.items()}


# ---------------------------------------------------------------------------
# Passe de cascade
# ---------------------------------------------------------------------------


class _Cascade:
    """État d'une passe de cascade : signatures non liées, index préchargés, compteurs, effets.

    `match` et `create` en instancient chacun une (fetch + prefetch frais) : aucune mémoire n'est partagée entre les deux étapes, `create` relit depuis la base l'état ferme posé par `match`. Les index sont tenus à jour en vif pendant la passe pour qu'une signature voie ce qu'une signature précédente de la **même** passe vient de poser.
    """

    def __init__(
        self,
        conn: Connection,
        queries: PersonsCreateQueries,
        logger: logging.Logger,
        *,
        person_repo: PersonRepository,
    ) -> None:
        self._logger = logger
        self._person_repo = person_repo

        in_perimeter = get_all_unlinked_authorships(conn, queries)
        out_of_perimeter = get_out_of_perimeter_candidates(conn, queries)
        self.authorships = in_perimeter + out_of_perimeter
        self.in_perimeter_total = len(in_perimeter)
        self.out_of_perimeter_total = len(out_of_perimeter)

        self._linked_index = load_linked_authorships_by_pub(conn, queries)
        self._idref_map = queries.fetch_idref_to_person_map(conn)
        self._orcid_map = queries.fetch_orcid_to_person_map(conn)
        self._hal_account_map = queries.fetch_hal_account_to_person_map(conn)
        self._name_form_map = queries.fetch_name_form_map(conn)
        self._name_form_status = queries.fetch_name_form_status_map(conn)
        self._rejected_by_pub = queries.fetch_rejected_person_ids_by_pub(conn)
        self._pub_max_authors = _max_authors_per_pub(self.authorships, self._linked_index)

        self.matched_counts: dict[str, int] = defaultdict(int)
        self.skipped_counts: dict[str, int] = defaultdict(int)
        self.created = 0
        self.out_of_perimeter_matched = 0
        self.corroboration_rejected = 0

    def _cross_and_name(
        self, a: EnrichedAuthorship
    ) -> tuple[int | None, NameFormDecision, frozenset[int]]:
        """Décision cross-source + forme de nom, contre les index vivants."""
        cross_source_match: int | None = None
        if a.publication_id is not None:
            candidates = self._linked_index.get((a.publication_id, a.author_position), [])
            if candidates:
                cross_source_match = decide_cross_source_match(
                    authorship_source=a.source,
                    last_norm=a.last_norm,
                    first_norm=a.first_norm,
                    candidates=candidates,
                    total_author_count=self._pub_max_authors.get(a.publication_id),
                )
        rejected_for_pub = (
            self._rejected_by_pub.get(a.publication_id, frozenset())
            if a.publication_id is not None
            else frozenset()
        )
        # Barreau name_form réservé au périmètre : hors-périmètre, un nom seul ne peut ni attacher ni créer (on n'a que des candidats ancrés sur identifiant ou position).
        if a.in_perimeter:
            norm = a.author_name_normalized
            name_form_outcome = decide_name_form_outcome(
                self._name_form_map.get(norm) if norm else None,
                a.allow_create,
                rejected_person_ids=rejected_for_pub,
            )
        else:
            name_form_outcome = NameFormDecision(action="skip", reason="out_of_perimeter")
        return cross_source_match, name_form_outcome, rejected_for_pub

    def decide_full(self, a: EnrichedAuthorship) -> PersonMatchDecision:
        """Décision complète, identifiants compris ; journalise la corroboration. Pour `match`."""
        cross_source_match, name_form_outcome, rejected_for_pub = self._cross_and_name(a)
        form = a.author_name_normalized
        idref_decision = decide_match_by_identifier(
            a.idref, self._idref_map, a.full_name, form, self._name_form_status
        )
        hal_decision = decide_match_by_identifier(
            a.hal_person_id, self._hal_account_map, a.full_name, form, self._name_form_status
        )
        # ORCID comme signal uniquement quand il est déposé par l'auteur (crossref / openalex raw_orcid / hal TEI) ; l'ORCID WoS, algorithmique, est ignoré ici (mais enregistré sur person_identifiers via add_identifiers).
        orcid_signal = a.orcid if a.source in ORCID_MATCH_SOURCES else None
        orcid_decision = decide_match_by_identifier(
            orcid_signal, self._orcid_map, a.full_name, form, self._name_form_status
        )
        for id_type, id_value, id_decision in (
            ("orcid", orcid_signal, orcid_decision),
            ("hal_person_id", a.hal_person_id, hal_decision),
            ("idref", a.idref, idref_decision),
        ):
            if id_decision.rejection is not None:
                rejected_pid, target_name = id_decision.rejection
                self._logger.info(
                    "  corroboration : identifiant %s=%s rejeté — « %s » incompatible avec la personne #%d (« %s »)",
                    id_type,
                    id_value,
                    a.full_name,
                    rejected_pid,
                    target_name,
                )
                self.corroboration_rejected += 1
        return decide_person_match(
            orcid_match=orcid_decision.person_id,
            hal_match=hal_decision.person_id,
            idref_match=idref_decision.person_id,
            cross_source_match=cross_source_match,
            name_form_outcome=name_form_outcome,
            rejected_person_ids=rejected_for_pub,
        )

    def decide_cross_and_name(self, a: EnrichedAuthorship) -> PersonMatchDecision:
        """Décision cross-source + nom seulement (sans identifiant). Pour `create` : les restantes n'ont aucun match identifiant, sinon `match` les aurait prises."""
        cross_source_match, name_form_outcome, rejected_for_pub = self._cross_and_name(a)
        return decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=cross_source_match,
            name_form_outcome=name_form_outcome,
            rejected_person_ids=rejected_for_pub,
        )

    def apply_match(self, a: EnrichedAuthorship, pid: int | None, reason: str) -> None:
        assert pid is not None  # garanti par decide_person_match action=match
        # `link_to_person` et `add_identifiers` consomment des dicts (API historique de `application.services.persons`) : conversion via `_asdict()` au boundary.
        a_dict = a._asdict()
        link_to_person(
            pid,
            [a_dict],
            repo=self._person_repo,
            resolution_mode=RESOLUTION_MODE_BY_REASON[reason],
        )
        add_name_form(pid, a.full_name, repo=self._person_repo)
        # Identifiants ajoutés en `pending` quelle que soit la source du match.
        add_identifiers(pid, [a_dict], repo=self._person_repo)
        self.matched_counts[reason] += 1
        if not a.in_perimeter:
            self.out_of_perimeter_matched += 1
        # Un membre ferme (identifiant, nom, création) ancre le cross-source de sa position ; un résultat cross-source, jamais — il n'ancre pas un autre cross-source.
        if a.publication_id is not None and reason != "cross_source":
            self._linked_index[(a.publication_id, a.author_position)].append(
                (pid, a.last_norm, a.first_norm, a.source)
            )

    def apply_create(self, a: EnrichedAuthorship) -> None:
        last = a.last_name or a.full_name or "?"
        first = a.first_name or ""
        marker = create_person(last, first, repo=self._person_repo)
        a_dict = a._asdict()
        link_to_person(marker, [a_dict], repo=self._person_repo, resolution_mode="name")
        add_identifiers(marker, [a_dict], repo=self._person_repo)
        add_name_form(marker, a.full_name, repo=self._person_repo)
        # Rendre la personne créée matchable dans la même passe par toutes ses formes — ordres ET initiales — via le générateur qui sert au peuplement de `person_name_forms`.
        # On fusionne dans les listes existantes : une forme déjà portée reste ambiguë (donc non matchée en aveugle), au lieu d'être détournée vers la dernière créée.
        for f in compute_person_name_forms(last, first):
            form_person_ids = self._name_form_map.setdefault(f, [])
            if marker not in form_person_ids:
                form_person_ids.append(marker)
        # La personne créée ancre aussi le cross-source de sa position, pour ses co-signatures.
        if a.publication_id is not None:
            self._linked_index[(a.publication_id, a.author_position)].append(
                (marker, a.last_norm, a.first_norm, a.source)
            )
        self.created += 1

    def result(self) -> CascadeResult:
        return CascadeResult(
            matched_counts=dict(self.matched_counts),
            skipped_counts=dict(self.skipped_counts),
            created=self.created,
            corroboration_rejected=self.corroboration_rejected,
            out_of_perimeter_matched=self.out_of_perimeter_matched,
            in_perimeter_total=self.in_perimeter_total,
            out_of_perimeter_total=self.out_of_perimeter_total,
        )


def _defer_create(cascade: _Cascade, authorship: EnrichedAuthorship) -> None:
    """No-op : dans la passe `match`, l'action `create` est différée à la passe `create` ; la signature reste non liée."""


def _run_pass(
    conn: Connection,
    queries: PersonsCreateQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
    decide: Callable[[_Cascade, EnrichedAuthorship], PersonMatchDecision],
    on_create: Callable[[_Cascade, EnrichedAuthorship], None],
) -> CascadeResult:
    """Squelette commun aux deux passes : instancie un `_Cascade` (fetch + prefetch frais), décide chaque signature via `decide` puis applique (match / create / skip).

    Seuls diffèrent la décision (`decide`) et le sort de l'action `create` (`on_create` : différée pour `match`, matérialisée pour `create`)."""
    logger.info("  chargement des index...")
    c = _Cascade(conn, queries, logger, person_repo=person_repo)
    total = len(c.authorships)
    logger.info("  %d signatures à traiter", total)
    for i, a in enumerate(c.authorships):
        if i and i % 5000 == 0:
            logger.info("  %d/%d signatures traitées", i, total)
        decision = decide(c, a)
        if decision.action == "match":
            c.apply_match(a, decision.person_id, decision.reason)
        elif decision.action == "create":
            on_create(c, a)
        else:
            c.skipped_counts[decision.reason] += 1
    return c.result()


def match(
    conn: Connection,
    queries: PersonsCreateQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
) -> CascadeResult:
    """Rattache les signatures non liées aux personnes existantes ou déjà résolues, sans créer."""
    logger.info("▶ match : rattachement aux personnes existantes ou déjà résolues")
    return _run_pass(
        conn,
        queries,
        logger,
        person_repo=person_repo,
        decide=_Cascade.decide_full,
        on_create=_defer_create,
    )


def create(
    conn: Connection,
    queries: PersonsCreateQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
) -> CascadeResult:
    """Reprend les signatures non liées : cross-source rejoué contre l'état ferme, puis création."""
    logger.info("▶ create : re-jugement cross-source puis création des inconnues")
    return _run_pass(
        conn,
        queries,
        logger,
        person_repo=person_repo,
        decide=_Cascade.decide_cross_and_name,
        on_create=_Cascade.apply_create,
    )
