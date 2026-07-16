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

`create` (2ᵉ passe) reprend les signatures restées non liées après `match` et les re-juge contre l'état ferme complet, **cross-source et forme de nom seulement** (les restantes n'ont aucun match identifiant, sinon `match` les aurait prises). Une à-créer peut ainsi rejoindre par cross-source une ancre d'une autre source de la même publication — deux graphies du même auteur aux formes disjointes (« Jean Martin » / « J-P Martin ») ne créent pas deux personnes selon l'ordre ; ne restent créées que les vraies inconnues. Les deux passes partagent le même `_Cascade` : `create` voit l'état ferme posé par `match` via les index tenus en mémoire, sans re-fetch.

Garde de rejet : les personnes rejetées pour la publication (`rejected_authorships`) sont éliminées des candidats à chaque signal — un match ne recrée pas une paire rejetée, et l'élimination peut désambiguïser un name form (2 candidats dont 1 rejeté → match univoque).
"""

import logging
from collections import defaultdict

from sqlalchemy import Connection

from application.pipeline.persons.loading import (
    EnrichedAuthorship,
    get_all_unlinked_authorships,
    get_cross_source_candidates,
    get_out_of_perimeter_candidates,
    load_linked_authorships_by_pub,
)
from application.pipeline.persons.metrics import CascadeResult
from application.ports.pipeline.persons.matching import PersonsMatchingQueries
from application.ports.repositories.person_repository import PersonRepository
from application.services.persons.core import (
    add_identifiers_from_authorships as add_identifiers,
    add_name_form,
    create_person,
    link_authorship,
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
# Passe de cascade
# ---------------------------------------------------------------------------


class _Cascade:
    """État d'une passe de cascade : signatures non liées, index préchargés, compteurs, effets.

    `match` et `create` en instancient chacun une (fetch + prefetch frais) : aucune mémoire n'est partagée entre les deux étapes, `create` relit depuis la base l'état ferme posé par `match`. Les index sont tenus à jour en vif pendant la passe pour qu'une signature voie ce qu'une signature précédente de la **même** passe vient de poser.
    """

    def __init__(
        self,
        conn: Connection,
        queries: PersonsMatchingQueries,
        logger: logging.Logger,
        *,
        person_repo: PersonRepository,
    ) -> None:
        self._logger = logger
        self._person_repo = person_repo

        in_perimeter = get_all_unlinked_authorships(conn, queries)
        out_of_perimeter = get_out_of_perimeter_candidates(conn, queries)
        cross_source = get_cross_source_candidates(conn, queries)
        self.authorships = in_perimeter + out_of_perimeter + cross_source
        self.in_perimeter_total = len(in_perimeter)
        self.out_of_perimeter_total = len(out_of_perimeter)
        # Signatures déjà liées en cross-source, re-jugées ce run. Celles qu'aucune passe ne re-résout (absentes de `resolved_cross_source_ids`) ont perdu leur ancre : la phase les détache.
        self.cross_source_candidate_ids = {a.authorship_id for a in cross_source}
        self.resolved_cross_source_ids: set[int] = set()

        self._linked_index = load_linked_authorships_by_pub(conn, queries)
        self._idref_map = queries.fetch_identifier_to_person_map(conn, "idref")
        self._orcid_map = queries.fetch_identifier_to_person_map(conn, "orcid")
        self._hal_account_map = queries.fetch_identifier_to_person_map(conn, "hal_person_id")
        self._name_form_map = queries.fetch_name_form_map(conn)
        self._name_form_status = queries.fetch_name_form_status_map(conn)
        self._rejected_by_pub = queries.fetch_rejected_person_ids_by_pub(conn)

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
        if a.current_person_id is not None:
            # Signature déjà liée en cross-source, re-jugée : couverte ce run, la phase ne la détache pas.
            self.resolved_cross_source_ids.add(a.authorship_id)
            if reason == "cross_source" and pid == a.current_person_id:
                return  # ré-affirmée à l'identique : pas d'écriture, pas d'ancrage, pas de compteur
        link_authorship(
            pid,
            a.source,
            a.authorship_id,
            repo=self._person_repo,
            resolution_mode=RESOLUTION_MODE_BY_REASON[reason],
        )
        add_name_form(pid, a.full_name, repo=self._person_repo)
        # `add_identifiers` reste une API batch (dict) partagée avec les CLI de maintenance ; conversion via `_asdict()` au boundary. Identifiants ajoutés en `pending` quelle que soit la source du match.
        add_identifiers(pid, [a._asdict()], repo=self._person_repo)
        self.matched_counts[reason] += 1
        if not a.in_perimeter:
            self.out_of_perimeter_matched += 1
        # Un membre ferme (identifiant, nom, création) ancre le cross-source de sa position ; un résultat cross-source, jamais — il n'ancre pas un autre cross-source.
        if a.publication_id is not None and reason != "cross_source":
            self._linked_index[(a.publication_id, a.author_position)].append(
                (pid, a.last_norm, a.first_norm, a.source)
            )

    def apply_create(self, a: EnrichedAuthorship) -> None:
        if a.current_person_id is not None:
            # Ancienne signature cross-source qui rejoint une création : couverte ce run.
            self.resolved_cross_source_ids.add(a.authorship_id)
        last = a.last_name or a.full_name or "?"
        first = a.first_name or ""
        marker = create_person(last, first, repo=self._person_repo)
        link_authorship(
            marker, a.source, a.authorship_id, repo=self._person_repo, resolution_mode="name"
        )
        add_identifiers(marker, [a._asdict()], repo=self._person_repo)
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
            cross_source_candidate_ids=self.cross_source_candidate_ids,
            resolved_cross_source_ids=self.resolved_cross_source_ids,
        )


def run_cascade(
    conn: Connection,
    queries: PersonsMatchingQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
) -> CascadeResult:
    """Rattache les signatures aux personnes, en deux passes sur un **seul** `_Cascade` (index vivants partagés — un seul fetch, un seul chargement).

    Passe `match` (`decide_full`) : rattachement ferme (identifiant, nom) et cross-source contre les ancres présentes ; les signatures non rattachées sont reprises en passe suivante. Passe `create` (`decide_cross_and_name`) sur ces seules restantes : cross-source de rattrapage contre l'état ferme complet, puis création des inconnues — une création ancre le cross-source d'une co-signature traitée juste après, dans la même passe.
    """
    logger.info("▶ chargement des index de la cascade...")
    c = _Cascade(conn, queries, logger, person_repo=person_repo)
    total = len(c.authorships)
    logger.info("  %d signatures à traiter", total)

    logger.info("▶ match : rattachement aux personnes existantes ou déjà résolues")
    unresolved: list[EnrichedAuthorship] = []
    for i, a in enumerate(c.authorships):
        if i and i % 5000 == 0:
            logger.info("  %d/%d signatures (match)", i, total)
        decision = c.decide_full(a)
        if decision.action == "match":
            c.apply_match(a, decision.person_id, decision.reason)
        else:
            unresolved.append(a)  # création différée ou aucun signal : reprise en passe create

    logger.info(
        "▶ create : création des personnes inconnues (%d signatures restantes)", len(unresolved)
    )
    for i, a in enumerate(unresolved):
        if i and i % 5000 == 0:
            logger.info("  %d/%d signatures (create)", i, len(unresolved))
        decision = c.decide_cross_and_name(a)
        if decision.action == "match":
            c.apply_match(a, decision.person_id, decision.reason)
        elif decision.action == "create":
            c.apply_create(a)
        else:
            c.skipped_counts[decision.reason] += 1
    return c.result()
