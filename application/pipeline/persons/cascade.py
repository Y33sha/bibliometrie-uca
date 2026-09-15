"""Cascade de rattachement des personnes aux `source_authorships` : `match` puis `create`.

Deux populations de candidats traversent la même cascade :

- **In-périmètre** (`source_authorships.in_perimeter = TRUE`) : authorships dont la source a détecté une affiliation dans le périmètre. Éligibles à tous les barreaux.
- **Hors-périmètre** ancrés (`in_perimeter = FALSE`) : rattachables sans forme de nom — identifiant fort partagé avec une personne connue, ou ancrage cross-source (même publication × position qu'un authorship déjà lié). Le barreau `person_name_forms` (match unique / création) y est neutralisé : un nom seul ne peut ni introduire ni attacher une personne hors-périmètre.

`match` interroge, pour chaque signature non liée, les signaux du plus fiable au moins fiable et rattache **sans jamais créer** :

1. **ORCID** déposé par l'auteur (sources de `ORCID_MATCH_SOURCES`).
2. **`hal_person_id`** — compte HAL, porté par les authorships HAL.
3. **IdRef**.
4. **Match par `person_name_forms`** — nom normalisé désignant une seule personne. Avant le cross-source, pour maximiser les ancres fermes que ce dernier exploite.
5. **Cross-source** — même publication × position, nom compatible ; inopérant au bootstrap.
6. **Initiales compatibles** — forme inconnue, mais une seule personne de même nom de famille aux initiales compatibles (`compatible_namesakes`).

Une personne au prénom réduit à des initiales prend le prénom plein compatible d'une signature qui la rejoint. Avant la cascade, `complete_reduced_first_names` lui donne le prénom plein que ses signatures attestent seul.

Un match par identifiant est **corroboré par le nom** : refusé (et journalisé) si le nom de la signature est incompatible avec le propriétaire de la valeur (identifiant recopié sur le mauvais co-auteur). Les signatures qu'aucun signal ne rattache — nom inconnu, ou ambigu — restent non liées.

`create` (2ᵉ passe) reprend les seules signatures **du périmètre** restées sans personne après `match`, et les re-juge **cross-source et forme de nom** (les restantes n'ont aucun match identifiant, sinon `match` les aurait prises). Une à-créer peut ainsi rejoindre par cross-source une ancre d'une autre source de la même publication — deux graphies du même auteur aux formes disjointes (« Jean Martin » / « J-P Martin ») ne créent pas deux personnes selon l'ordre ; ne restent créées que les vraies inconnues. Les signatures qui ne peuvent pas créer de personne — rôle exclu, forme de nom ambiguë — passent après les créations : seul un rattachement cross-source leur reste possible, et elles reçoivent ainsi tous les ancrages de la passe. Les deux passes partagent le même `_Cascade` : `create` voit l'état ferme posé par `match` via les index tenus en mémoire, sans re-fetch.

Hors périmètre, seule une création poserait une ancre nouvelle pendant `create` — une identification cross-source n'en pose jamais. Ces signatures n'ont donc rien à y gagner : la passe `match` du run suivant les rejuge contre l'état complet.

Garde de rejet : les personnes rejetées pour la publication (`rejected_authorships`) sont éliminées des candidats à chaque signal — un match ne recrée pas une paire rejetée, et l'élimination peut désambiguïser un name form (2 candidats dont 1 rejeté → match univoque).
"""

import logging
from collections import defaultdict

from sqlalchemy import Connection

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from application.pipeline.persons.first_names import complete_reduced_first_names
from application.pipeline.persons.loading import (
    EnrichedAuthorship,
    get_all_unlinked_authorships,
    get_cross_source_candidates,
    get_out_of_perimeter_candidates,
    load_linked_authorships_by_pub,
)
from application.pipeline.persons.metrics import CascadeResult, log_matching_breakdown
from application.pipeline.progression import attente, progression
from application.ports.pipeline.persons.matching import PersonsMatchingQueries
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from application.services.persons.core import (
    add_identifiers_from_authorships as add_identifiers,
    add_name_form,
    create_person,
    link_authorship,
    update_name,
)
from domain.normalize import normalize_name
from domain.persons.matching import (
    ORCID_MATCH_SOURCES,
    RESOLUTION_MODE_BY_REASON,
    NameFormDecision,
    Namesake,
    PersonMatchDecision,
    compatible_namesakes,
    decide_cross_source_match,
    decide_match_by_identifier,
    decide_name_form_outcome,
    decide_person_match,
)
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.name_matching import first_name_initials, initials_extend

# ---------------------------------------------------------------------------
# Passe de cascade
# ---------------------------------------------------------------------------


class _Cascade:
    """État de la cascade : signatures non liées, index préchargés, compteurs, effets.

    Un seul `_Cascade` sert aux deux passes : un fetch, un chargement d'index. Les index sont tenus à jour en vif, si bien qu'une signature voit ce qu'une signature précédente vient de poser, y compris depuis la passe `match`.
    """

    def __init__(
        self,
        conn: Connection,
        queries: PersonsMatchingQueries,
        *,
        person_repo: PersonRepository,
        authorship_repo: AuthorshipRepository,
        conflicting: frozenset[int] = frozenset(),
    ) -> None:
        self._person_repo = person_repo
        self._authorship_repo = authorship_repo

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
        # Personnes par nom de famille normalisé, pour le rattachement par initiales compatibles.
        self._namesakes: dict[str, list[Namesake]] = defaultdict(list)
        self._namesake_of: dict[int, Namesake] = {}
        for namesake in queries.fetch_namesakes(conn):
            self._index_namesake(namesake._replace(conflicting=namesake.person_id in conflicting))
        self.first_names_completed = 0

        self.matched_counts: dict[str, int] = defaultdict(int)
        self.skipped_counts: dict[str, int] = defaultdict(int)
        self.created = 0
        self.out_of_perimeter_matched = 0
        self.corroboration_rejected = 0
        # Identifiants distincts refusés. Une même signature revient sur chaque publication
        # d'une collaboration : le compteur d'occurrences en dit surtout la fréquence, pas
        # l'ampleur — c'est le nombre d'identifiants concernés qui la mesure.
        self.corroboration_rejected_ids: set[tuple[str, str]] = set()

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
        rejected_for_pub = self._rejected_for(a)
        # Barreau name_form réservé au périmètre : hors-périmètre, un nom seul ne peut ni attacher ni créer (on n'a que des candidats ancrés sur identifiant ou position).
        if a.in_perimeter:
            name_form_outcome = self._name_form_outcome(a, rejected_for_pub)
        else:
            name_form_outcome = NameFormDecision(action="skip", reason="out_of_perimeter")
        return cross_source_match, name_form_outcome, rejected_for_pub

    def _rejected_for(self, a: EnrichedAuthorship) -> frozenset[int]:
        """Personnes rejetées pour la publication de la signature."""
        if a.publication_id is None:
            return frozenset()
        return self._rejected_by_pub.get(a.publication_id, frozenset())

    def _name_form_outcome(
        self, a: EnrichedAuthorship, rejected_for_pub: frozenset[int]
    ) -> NameFormDecision:
        """Décision par la forme du nom, contre l'index vivant des formes ; à forme inconnue, par les initiales compatibles."""
        norm = a.author_name_normalized
        person_ids = self._name_form_map.get(norm) if norm else None
        compatible = (
            compatible_namesakes(a.first_name, self._namesakes.get(a.last_norm, []))
            if person_ids is None
            else []
        )
        return decide_name_form_outcome(
            person_ids,
            a.allow_create,
            rejected_person_ids=rejected_for_pub,
            compatible_person_ids=compatible,
        )

    def name_form_ambiguous(self, a: EnrichedAuthorship) -> bool:
        """Vrai quand la forme du nom ne désigne aucune personne unique parmi celles qui la portent : la signature ne peut ni se rattacher par son nom, ni créer de personne."""
        return self._name_form_outcome(a, self._rejected_for(a)).reason == "ambiguous_name_form"

    def decide_full(self, a: EnrichedAuthorship) -> PersonMatchDecision:
        """Décision complète, identifiants compris ; compte les refus de corroboration. Pour `match`."""
        cross_source_match, name_form_outcome, rejected_for_pub = self._cross_and_name(a)
        form = a.author_name_normalized
        idref_decision = decide_match_by_identifier(
            a.idref, self._idref_map, a.full_name, form, self._name_form_status
        )
        hal_decision = decide_match_by_identifier(
            a.hal_person_id, self._hal_account_map, a.full_name, form, self._name_form_status
        )
        # ORCID comme signal seulement depuis les sources à dépôt auteur (`ORCID_MATCH_SOURCES`) ; les autres restent enregistrés sur person_identifiers via add_identifiers.
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
                self.corroboration_rejected += 1
                if id_value is not None:
                    self.corroboration_rejected_ids.add((id_type, id_value))
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

    def resolve_or_create(self, a: EnrichedAuthorship) -> bool:
        """Rattache, crée ou écarte la signature d'après la décision cross-source et nom. Rend `True` sur une création."""
        decision = self.decide_cross_and_name(a)
        if decision.action == "match":
            self.apply_match(a, decision.person_id, decision.reason)
        elif decision.action == "create":
            self.apply_create(a)
            return True
        else:
            self.skipped_counts[decision.reason] += 1
        return False

    def apply_match(self, a: EnrichedAuthorship, pid: int | None, reason: str) -> bool:
        """Rattache la signature à `pid`. Rend `False` quand elle confirme à l'identique un rattachement cross-source existant, sans rien écrire."""
        assert pid is not None  # garanti par decide_person_match action=match
        if a.current_person_id is not None:
            # Signature déjà liée en cross-source, re-jugée : couverte ce run, la phase ne la détache pas.
            self.resolved_cross_source_ids.add(a.authorship_id)
            if reason == "cross_source" and pid == a.current_person_id:
                return False  # ré-affirmée à l'identique : pas d'écriture, pas d'ancrage, pas de compteur
        link_authorship(
            pid,
            a.source,
            a.authorship_id,
            repo=self._authorship_repo,
            resolution_mode=RESOLUTION_MODE_BY_REASON[reason],
        )
        add_name_form(pid, a.full_name, repo=self._person_repo)
        # `add_identifiers` reste une API batch (dict) partagée avec les CLI de maintenance ; conversion via `_asdict()` au boundary. Identifiants ajoutés en `pending` quelle que soit la source du match.
        add_identifiers(pid, [a._asdict()], repo=self._person_repo)
        self._complete_first_name(pid, a)
        self.matched_counts[reason] += 1
        if not a.in_perimeter:
            self.out_of_perimeter_matched += 1
        # Un membre ferme (identifiant, nom, création) ancre le cross-source de sa position ; un résultat cross-source, jamais — il n'ancre pas un autre cross-source.
        if a.publication_id is not None and reason != "cross_source":
            self._linked_index[(a.publication_id, a.author_position)].append(
                (pid, a.last_norm, a.first_norm, a.source)
            )
        return True

    def apply_create(self, a: EnrichedAuthorship) -> None:
        if a.current_person_id is not None:
            # Ancienne signature cross-source qui rejoint une création : couverte ce run.
            self.resolved_cross_source_ids.add(a.authorship_id)
        last = a.last_name or a.full_name
        first = a.first_name or ""
        marker = create_person(last, first, repo=self._person_repo)
        link_authorship(
            marker, a.source, a.authorship_id, repo=self._authorship_repo, resolution_mode="name"
        )
        add_identifiers(marker, [a._asdict()], repo=self._person_repo)
        add_name_form(marker, a.full_name, repo=self._person_repo)
        self._index_namesake(Namesake(marker, last, first))
        # La personne créée ancre aussi le cross-source de sa position, pour ses co-signatures.
        if a.publication_id is not None:
            self._linked_index[(a.publication_id, a.author_position)].append(
                (marker, a.last_norm, a.first_norm, a.source)
            )
        self.created += 1

    def _index_namesake(self, namesake: Namesake) -> None:
        """Rend la personne matchable dans la même passe par son nom de famille, et par toutes les formes de son nom — ordres ET initiales — via le générateur qui sert au peuplement de `person_name_forms`.

        Les formes fusionnent dans les listes existantes : une forme déjà portée reste ambiguë (donc non matchée en aveugle), au lieu d'être détournée vers la dernière personne indexée.
        """
        previous = self._namesake_of.get(namesake.person_id)
        same_last_name = self._namesakes[normalize_name(namesake.last_name)]
        if previous is not None:
            same_last_name.remove(previous)
        same_last_name.append(namesake)
        self._namesake_of[namesake.person_id] = namesake
        for f in compute_person_name_forms(namesake.last_name, namesake.first_name):
            form_person_ids = self._name_form_map.setdefault(f, [])
            if namesake.person_id not in form_person_ids:
                form_person_ids.append(namesake.person_id)

    def _complete_first_name(self, pid: int, a: EnrichedAuthorship) -> None:
        """Donne à une personne au prénom réduit le prénom plein compatible de la signature qui la rejoint (« Tnourji A. » → « Tnourji Abdellah ») : une signature d'un autre prénom plein ne s'y rattache plus par ses initiales."""
        namesake = self._namesake_of.get(pid)
        if namesake is None or namesake.conflicting:
            return
        initials = first_name_initials(namesake.first_name)
        if (
            initials is None
            or normalize_name(namesake.last_name) != a.last_norm
            or first_name_initials(a.first_name) is not None
            or not initials_extend(initials, a.first_name)
        ):
            return
        update_name(pid, namesake.last_name, a.first_name, repo=self._person_repo)
        self._index_namesake(namesake._replace(first_name=a.first_name))
        self.first_names_completed += 1

    def result(self) -> CascadeResult:
        return CascadeResult(
            matched_counts=dict(self.matched_counts),
            skipped_counts=dict(self.skipped_counts),
            created=self.created,
            corroboration_rejected=self.corroboration_rejected,
            corroboration_rejected_distinct=len(self.corroboration_rejected_ids),
            out_of_perimeter_matched=self.out_of_perimeter_matched,
            in_perimeter_total=self.in_perimeter_total,
            out_of_perimeter_total=self.out_of_perimeter_total,
            cross_source_candidate_ids=self.cross_source_candidate_ids,
            resolved_cross_source_ids=self.resolved_cross_source_ids,
            first_names_completed=self.first_names_completed,
        )


def run_cascade(
    conn: Connection,
    queries: PersonsMatchingQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
    authorship_repo: AuthorshipRepository,
) -> CascadeResult:
    """Rattache les signatures aux personnes, en deux passes sur un **seul** `_Cascade` (index vivants partagés — un seul fetch, un seul chargement).

    Passe `match` (`decide_full`) : rattachement ferme (identifiant, nom) et cross-source contre les ancres présentes ; les signatures non rattachées sont reprises en passe suivante.

    Passe `create` (`decide_cross_and_name`) sur les seules signatures du périmètre restées sans personne : cross-source et nom contre l'état ferme complet, puis création des inconnues. Une création ancre le cross-source d'une co-signature traitée juste après, dans la même passe — sans quoi deux graphies du même auteur inconnu produiraient deux personnes.
    """
    etape(logger, "Identification des personnes")
    completion = complete_reduced_first_names(conn, queries, person_repo=person_repo)
    logger.info(
        "%s%s d'après les signatures",
        BRANCHE,
        accord(completion.completed, "prénom complété", "prénoms complétés"),
    )
    # Le chargement des index précède tout affichage de volume : il dure, et la phase resterait
    # muette jusqu'à ce qu'il rende la main.
    with attente(f"{BRANCHE}chargement des signatures", logger) as ligne:
        c = _Cascade(
            conn,
            queries,
            person_repo=person_repo,
            authorship_repo=authorship_repo,
            conflicting=completion.conflicting,
        )
        c.first_names_completed = completion.completed
        total = len(c.authorships)
        ligne.conclut(f"{BRANCHE}{accord(total, 'signature')} à examiner")

    unresolved: list[EnrichedAuthorship] = []
    with progression(total, BRANCHE.rstrip(), logger, compte_retenus=True) as avancement:
        for a in c.authorships:
            avancement.avance()
            decision = c.decide_full(a)
            if decision.action == "match":
                # La barre compte les rattachements réels, pas les confirmations à l'identique.
                if c.apply_match(a, decision.person_id, decision.reason):
                    avancement.retient()
            else:
                # Création différée ou aucun signal : reprise en passe create.
                unresolved.append(a)

    log_matching_breakdown(logger, c.result())

    # Seules les signatures du périmètre encore sans personne peuvent en créer une. Les autres —
    # hors périmètre, ou déjà liées en cross-source — n'attendent de cette passe qu'un
    # rattachement à une personne qu'elle vient de créer ; la passe suivante du run d'après les
    # rejuge contre l'état ferme complet.
    sans_personne = [a for a in unresolved if a.in_perimeter and a.current_person_id is None]
    non_identifiees = [a for a in sans_personne if a.allow_create]
    # Une création ajoute des personnes aux formes de nom sans en retirer : une forme ambiguë le reste.
    indecidables = [a for a in non_identifiees if c.name_form_ambiguous(a)]
    indecidables_ids = {a.authorship_id for a in indecidables}
    a_creer = [a for a in non_identifiees if a.authorship_id not in indecidables_ids]

    etape(logger, "Création de nouvelles personnes")
    logger.info(
        "%s%s %s",
        BRANCHE,
        accord(len(non_identifiees), "signature"),
        forme(len(non_identifiees), "non identifiée"),
    )
    logger.info("%s%s (forme de nom ambiguë)", BRANCHE, accord(len(indecidables), "indécidable"))
    creees_avant = c.created
    with progression(len(a_creer), BRANCHE.rstrip(), logger, compte_retenus=True) as avancement:
        for a in a_creer:
            avancement.avance()
            if c.resolve_or_create(a):
                avancement.retient()
    # Les signatures qui ne peuvent pas créer de personne — rôle exclu, forme de nom ambiguë —
    # peuvent encore rejoindre en cross-source une personne créée pour une co-signature. Traitées
    # après toutes les créations, elles en reçoivent tous les ancrages.
    for a in [*(a for a in sans_personne if not a.allow_create), *indecidables]:
        c.resolve_or_create(a)
    logger.info(
        "%s%s %s",
        DERNIERE_BRANCHE,
        accord(c.created - creees_avant, "personne"),
        forme(c.created - creees_avant, "créée"),
    )
    return c.result()
