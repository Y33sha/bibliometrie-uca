"""Cascade de rattachement des personnes aux `source_contributions` : `match` puis `create`.

Deux populations de candidats traversent la même cascade :

- **In-périmètre** (`source_contributions.in_perimeter = TRUE`) : contributions dont la source a détecté une affiliation dans le périmètre. Éligibles à tous les barreaux.
- **Hors-périmètre** ancrés (`in_perimeter = FALSE`) : rattachables sans forme de nom — identifiant fort partagé avec une personne connue, ou ancrage cross-source (même groupe de contributions sources qu'une contribution déjà lié). Le barreau `person_name_forms` (match unique / création) y est neutralisé : un nom seul ne peut ni introduire ni attacher une personne hors-périmètre.

`match` interroge, pour chaque contribution source non liée, les signaux du plus fiable au moins fiable et rattache **sans jamais créer** :

1. **ORCID** déposé par l'auteur (sources de `ORCID_MATCH_SOURCES`).
2. **`hal_person_id`** — compte HAL, porté par les contributions HAL.
3. **IdRef**.
4. **Match par `person_name_forms`** — nom normalisé désignant une seule personne, dans l'ordre « prénom nom » puis, pour une contribution source au nom et prénom inversés, « nom prénom » ; à forme inconnue, seule personne de même nom de famille aux initiales compatibles (`compatible_persons`), le nom de famille pouvant être tout groupe de mots final de la contribution source (« Florence Caldefie Chezet » rejoint « Caldefie-Chezet F. »). Avant le cross-source, pour maximiser les ancres fermes que ce dernier exploite.
5. **Cross-source** — même groupe de contributions sources, nom compatible ; inopérant au bootstrap.

Une personne au prénom réduit à des initiales prend le prénom plein compatible d'une contribution source qui la rejoint. Avant la cascade, `complete_reduced_first_names` lui donne le prénom plein que ses contributions sources attestent seul.

Un match par identifiant est **corroboré par le nom** : refusé (et journalisé) si le nom de la contribution source est incompatible avec le propriétaire de la valeur (identifiant recopié sur le mauvais co-auteur). Les contributions sources qu'aucun signal ne rattache — nom inconnu, ou ambigu — restent non liées.

`create` (2ᵉ passe) reprend les seules contributions sources **du périmètre** restées sans personne après `match`, et les re-juge **cross-source et forme de nom** (les restantes n'ont aucun match identifiant, sinon `match` les aurait prises). Une à-créer peut ainsi rejoindre par cross-source une ancre d'une autre source de la même publication — deux graphies du même auteur aux formes disjointes (« Jean Martin » / « J-P Martin ») ne créent pas deux personnes selon l'ordre ; ne restent créées que les vraies inconnues. Les contributions sources dont la source sépare nom et prénom passent en premier : une personne créée prend le découpage de la source plutôt que celui du parseur. Les contributions sources qui ne peuvent pas créer de personne — rôle exclu, forme de nom ambiguë — passent après les créations : seul un rattachement cross-source leur reste possible, et elles reçoivent ainsi tous les ancrages de la passe. Les deux passes partagent le même `_Cascade` : `create` voit l'état ferme posé par `match` via les index tenus en mémoire, sans re-fetch. La cascade écrit les personnes et les rattachements des contributions sources ; `person_name_forms` est synchronisée après elle (`populate_person_name_forms`).

Hors périmètre, seule une création poserait une ancre nouvelle pendant `create` — une identification cross-source n'en pose jamais. Ces contributions sources n'ont donc rien à y gagner : la passe `match` du run suivant les rejuge contre l'état complet.

Garde de rejet : les personnes rejetées pour la publication (`rejected_contributions`) sont éliminées des candidats à chaque signal — un match ne recrée pas une paire rejetée, et l'élimination peut désambiguïser un name form (2 candidats dont 1 rejeté → match univoque).
"""

import logging
from collections import defaultdict

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.persons.identifiers import (
    AttributionStatus,
    PersonIdentifierType,
)
from domain.persons.matching import (
    RESOLUTION_MODE_BY_REASON,
    UNDECIDABLE_NAME_FORM_REASONS,
    IdentifiedPerson,
    MatchReason,
    NameFormDecision,
    Namesake,
    PersonMatchDecision,
    compatible_persons,
    decide_cross_source_match,
    decide_match_by_identifier,
    decide_name_form_outcome,
    decide_person_match,
    trusted_identifier,
)
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE, compute_person_name_forms
from domain.persons.name_matching import first_name_initials, full_first_name_extends
from domain.persons.person import validated_name
from domain.sources.registry import require_known_source
from infrastructure.repositories.person_repository import PgPersonRepository
from infrastructure.sql_fragments import (
    REJECTED_PAIRS,
    active_name_form,
)
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from pipeline.runtime.observability.progression import attente, progression
from pipeline.transformation.persons.first_names import complete_reduced_first_names
from pipeline.transformation.persons.loading import (
    EnrichedContribution,
    get_all_unlinked_contributions,
    get_cross_source_candidates,
    get_out_of_perimeter_candidates,
    load_linked_contributions_by_group,
)
from pipeline.transformation.persons.metrics import CascadeResult, log_matching_breakdown
from pipeline.transformation.persons.person_writes import (
    add_identifiers_from_contributions as add_identifiers,
)
from pipeline.transformation.persons.store import PersonsStore


def fetch_identifier_to_person_map(conn: Connection, id_type: str) -> dict[str, IdentifiedPerson]:
    """Le nom normalisé de la personne ciblée accompagne le `person_id` : la cascade corrobore le match identifiant par le nom (`decide_match_by_identifier`), et refuse l'identifiant d'une contribution source étrangère."""
    rows = conn.execute(
        text(f"""
            SELECT pi.id_value, pi.person_id,
                   p.last_name_normalized AS ln, p.first_name_normalized AS fn
            FROM person_identifiers pi
            JOIN persons p ON p.id = pi.person_id
            WHERE pi.id_type = :id_type
              AND pi.status != '{AttributionStatus.REJECTED.value}'
        """),
        {"id_type": id_type},
    ).all()
    return {r.id_value: IdentifiedPerson(r.person_id, r.ln or "", r.fn or "") for r in rows}


def fetch_name_form_map(conn: Connection) -> dict[str, list[int]]:
    """Agrégation par `name_form` sur la table dénormalisée `(name_form, person_id, sources[], status)` : un dict trié par `person_id` croissant pour stabilité. Les liens `status = 'rejected'` sont exclus : une forme de nom rejetée pour une personne reste écartée du matching par nom (verrou de non-retour). Une forme dérivée du nom de la personne reste toujours active."""
    rows = conn.execute(
        text(f"""
            SELECT name_form,
                   array_agg(person_id ORDER BY person_id) AS person_ids
            FROM person_name_forms
            WHERE {active_name_form("person_name_forms")}
            GROUP BY name_form
        """)
    ).all()
    return {r.name_form: r.person_ids for r in rows}


def fetch_name_form_status_map(conn: Connection) -> dict[tuple[str, int], str]:
    """Sert à la corroboration du matching par identifiant : quand un identifiant résout vers une personne, le verdict du couple (forme de la contribution source, personne) tranche sans test de compatibilité de nom — `confirmed` corrobore, `rejected` refuse ; en l'absence de verdict, on retombe sur la comparaison par tokens.

    Le verdict combine le statut admin et la provenance de la forme : une forme dérivée du nom de la personne (`'persons' ∈ sources`) corrobore toujours ; sinon un rejet admin refuse et une confirmation admin (`status = 'confirmed'`) corrobore. Les formes seulement `pending` et non dérivées du nom sont omises.
    """
    rows = conn.execute(
        text(f"""
            SELECT name_form, person_id,
                   CASE WHEN '{CANONICAL_NAME_FORM_SOURCE}' = ANY(sources)
                        THEN '{AttributionStatus.CONFIRMED.value}'
                        WHEN status = '{AttributionStatus.REJECTED.value}'
                        THEN '{AttributionStatus.REJECTED.value}'
                        ELSE '{AttributionStatus.CONFIRMED.value}' END AS status
            FROM person_name_forms
            WHERE status = '{AttributionStatus.REJECTED.value}'
               OR status = '{AttributionStatus.CONFIRMED.value}'
               OR '{CANONICAL_NAME_FORM_SOURCE}' = ANY(sources)
        """)
    ).all()
    return {(r.name_form, r.person_id): r.status for r in rows}


def fetch_rejected_person_ids_by_publication(conn: Connection) -> dict[int, frozenset[int]]:
    """Garde de matching : une paire `(publication, personne)` rejetée reste hors de portée de la cascade, jamais re-rattachée. Une publication est rejetée pour une personne dès qu'un de ses enregistrements sources l'est. Le caller élimine ces personnes des candidats (cf. `domain.persons.matching.decide_person_match` et `decide_name_form_outcome`)."""
    rows = conn.execute(
        text(f"""
            SELECT publication_id, array_agg(DISTINCT person_id) AS person_ids
            FROM ({REJECTED_PAIRS}) rp
            WHERE publication_id IS NOT NULL
            GROUP BY publication_id
        """)
    ).all()
    return {r.publication_id: frozenset(r.person_ids) for r in rows}


_LINK_CONTRIBUTION = text("""
    UPDATE source_contributions
    SET person_id = :pid, resolution_mode = CAST(:mode AS resolution_mode)
    WHERE id = :aid AND source = :src
""")


def link_contribution(
    conn: Connection, person_id: int, source: str, source_contribution_id: int, resolution_mode: str
) -> None:
    """Rattache une contribution source à une personne, avec le canal de résolution (`identifier`, `name` ou `cross_source`). Lève `ValidationError` sur une source hors registre."""
    require_known_source(source)
    conn.execute(
        _LINK_CONTRIBUTION,
        {"pid": person_id, "aid": source_contribution_id, "src": source, "mode": resolution_mode},
    )


# ---------------------------------------------------------------------------
# Passe de cascade
# ---------------------------------------------------------------------------


class _Cascade:
    """État de la cascade : contributions sources non liées, index préchargés, compteurs, effets.

    Un seul `_Cascade` sert aux deux passes : un fetch, un chargement d'index. Les index sont tenus à jour en vif, si bien qu'une contribution source voit ce qu'une contribution source précédente vient de poser, y compris depuis la passe `match`.
    """

    def __init__(
        self,
        conn: Connection,
        *,
        repo: PgPersonRepository,
        conflicting: frozenset[int] = frozenset(),
    ) -> None:
        self._conn = conn
        self._repo = repo

        in_perimeter = get_all_unlinked_contributions(conn)
        out_of_perimeter = get_out_of_perimeter_candidates(conn)
        cross_source = get_cross_source_candidates(conn)
        self.contributions = in_perimeter + out_of_perimeter + cross_source
        self.in_perimeter_total = len(in_perimeter)
        self.out_of_perimeter_total = len(out_of_perimeter)
        # Contributions sources déjà liées en cross-source, re-jugées ce run. Celles qu'aucune passe ne re-résout (absentes de `resolved_cross_source_ids`) ont perdu leur ancre : la phase les détache.
        self.cross_source_candidate_ids = {a.source_contribution_id for a in cross_source}
        self.resolved_cross_source_ids: set[int] = set()

        self._linked_index = load_linked_contributions_by_group(conn)
        self._idref_map = fetch_identifier_to_person_map(conn, "idref")
        self._orcid_map = fetch_identifier_to_person_map(conn, "orcid")
        self._hal_account_map = fetch_identifier_to_person_map(conn, "hal_person_id")
        self._name_form_map = fetch_name_form_map(conn)
        self._name_form_status = fetch_name_form_status_map(conn)
        self._rejected_by_publication = fetch_rejected_person_ids_by_publication(conn)
        # Personnes par nom de famille normalisé, pour le rattachement par initiales compatibles.
        self._namesakes: dict[str, list[Namesake]] = defaultdict(list)
        self._namesake_of: dict[int, Namesake] = {}
        for namesake in PersonsStore(conn).namesakes():
            self._index_namesake(namesake._replace(conflicting=namesake.person_id in conflicting))
        self.first_names_completed = 0
        # Contributions sources du périmètre restées sans personne en passe `create`, avec le motif du `skip`.
        self.orphans: list[tuple[EnrichedContribution, str]] = []

        self.matched_counts: dict[str, int] = defaultdict(int)
        self.skipped_counts: dict[str, int] = defaultdict(int)
        self.created = 0
        self.out_of_perimeter_matched = 0
        self.corroboration_rejected = 0
        # Identifiants distincts refusés. Une même contribution source revient sur chaque publication
        # d'une collaboration : le compteur d'occurrences en dit surtout la fréquence, pas
        # l'ampleur — c'est le nombre d'identifiants concernés qui la mesure.
        self.corroboration_rejected_ids: set[tuple[str, str]] = set()

    def _cross_and_name(
        self, a: EnrichedContribution
    ) -> tuple[int | None, NameFormDecision, frozenset[int]]:
        """Décision cross-source + forme de nom, contre les index vivants."""
        cross_source_match: int | None = None
        if a.group_id is not None:
            candidates = self._linked_index.get(a.group_id, [])
            if candidates:
                cross_source_match = decide_cross_source_match(
                    contribution_source=a.source,
                    last_norm=a.last_norm,
                    first_norm=a.first_norm,
                    candidates=candidates,
                )
        rejected_for_publication = self._rejected_for(a)
        # Barreau name_form réservé au périmètre : hors-périmètre, un nom seul ne peut ni attacher ni créer (les candidats sont ancrés sur un identifiant ou un groupe).
        if a.in_perimeter:
            name_form_outcome = self._name_form_outcome(a, rejected_for_publication)
        else:
            name_form_outcome = NameFormDecision(action="skip", reason=MatchReason.OUT_OF_PERIMETER)
        return cross_source_match, name_form_outcome, rejected_for_publication

    def _rejected_for(self, a: EnrichedContribution) -> frozenset[int]:
        """Personnes rejetées pour la publication de la contribution source."""
        if a.publication_id is None:
            return frozenset()
        return self._rejected_by_publication.get(a.publication_id, frozenset())

    def _name_form_outcome(
        self, a: EnrichedContribution, rejected_for_publication: frozenset[int]
    ) -> NameFormDecision:
        """Décision par la forme du nom, contre l'index vivant des formes ; à forme inconnue, par les initiales compatibles."""
        person_ids = next(
            (self._name_form_map[f] for f in a.name_forms if f in self._name_form_map), None
        )
        compatible = compatible_persons(a.name, self._namesakes) if person_ids is None else []
        return decide_name_form_outcome(
            person_ids,
            a.allow_create,
            rejected_person_ids=rejected_for_publication,
            compatible_person_ids=compatible,
        )

    def name_form_undecidable(self, a: EnrichedContribution) -> bool:
        """Vrai quand la forme du nom est connue mais ne désigne aucune personne unique, par homonymie ou parce que toutes ses personnes sont rejetées pour la publication : la contribution source ne peut ni se rattacher par son nom, ni créer de personne."""
        return (
            self._name_form_outcome(a, self._rejected_for(a)).reason
            in UNDECIDABLE_NAME_FORM_REASONS
        )

    def decide_full(self, a: EnrichedContribution) -> PersonMatchDecision:
        """Décision complète, identifiants compris ; compte les refus de corroboration. Pour `match`."""
        cross_source_match, name_form_outcome, rejected_for_publication = self._cross_and_name(a)
        idref = a.identifiers.get(PersonIdentifierType.IDREF)
        hal_person_id = a.identifiers.get(PersonIdentifierType.HAL_PERSON_ID)
        idref_decision = decide_match_by_identifier(
            idref, self._idref_map, a.name, a.name_forms, self._name_form_status
        )
        hal_decision = decide_match_by_identifier(
            hal_person_id, self._hal_account_map, a.name, a.name_forms, self._name_form_status
        )
        # Un ORCID d'une source sans dépôt par l'auteur reste enregistré sur person_identifiers (add_identifiers), sans servir de signal.
        orcid_signal = (
            a.identifiers.get(PersonIdentifierType.ORCID)
            if trusted_identifier(PersonIdentifierType.ORCID, a.source)
            else None
        )
        orcid_decision = decide_match_by_identifier(
            orcid_signal, self._orcid_map, a.name, a.name_forms, self._name_form_status
        )
        for id_type, id_value, id_decision in (
            ("orcid", orcid_signal, orcid_decision),
            ("hal_person_id", hal_person_id, hal_decision),
            ("idref", idref, idref_decision),
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
            rejected_person_ids=rejected_for_publication,
        )

    def decide_cross_and_name(self, a: EnrichedContribution) -> PersonMatchDecision:
        """Décision cross-source + nom seulement (sans identifiant). Pour `create` : les restantes n'ont aucun match identifiant, sinon `match` les aurait prises."""
        cross_source_match, name_form_outcome, rejected_for_publication = self._cross_and_name(a)
        return decide_person_match(
            orcid_match=None,
            hal_match=None,
            idref_match=None,
            cross_source_match=cross_source_match,
            name_form_outcome=name_form_outcome,
            rejected_person_ids=rejected_for_publication,
        )

    def resolve_or_create(self, a: EnrichedContribution) -> bool:
        """Rattache, crée ou écarte la contribution source d'après la décision cross-source et nom. Rend `True` sur une création."""
        decision = self.decide_cross_and_name(a)
        if decision.action == "match":
            self.apply_match(a, decision.person_id, decision.reason)
        elif decision.action == "create":
            self.apply_create(a)
            return True
        else:
            assert decision.reason is not None  # garanti par decide_name_form_outcome action=skip
            self.skipped_counts[decision.reason] += 1
            self.orphans.append((a, decision.reason))
        return False

    def log_orphans(self, orphans_log: logging.Logger) -> None:
        """Écrit une ligne par contribution source restée sans personne : motif, personnes que désignent ses formes de nom, personnes aux initiales compatibles, personnes rejetées pour la publication. Les contributions sources dont la création est interdite (jurys de thèse) sont omises."""
        for a, reason in self.orphans:
            if reason == MatchReason.CREATION_NOT_ALLOWED:
                continue
            forms = {f: self._name_form_map.get(f) for f in a.name_forms}
            orphans_log.info(
                "contribution source %d (%s) « %s » : %s ; formes %s ; initiales compatibles %s ; rejetées pour la publication %s",
                a.source_contribution_id,
                a.source,
                a.name.display(),
                reason,
                forms,
                compatible_persons(a.name, self._namesakes),
                sorted(self._rejected_for(a)),
            )

    def apply_match(
        self, a: EnrichedContribution, pid: int | None, reason: MatchReason | None
    ) -> bool:
        """Rattache la contribution source à `pid`. Rend `False` quand elle confirme à l'identique un rattachement cross-source existant, sans rien écrire."""
        assert (
            pid is not None and reason is not None
        )  # garantis par decide_person_match action=match
        if a.current_person_id is not None:
            # Contribution source déjà liée en cross-source, re-jugée : couverte ce run, la phase ne la détache pas.
            self.resolved_cross_source_ids.add(a.source_contribution_id)
            if reason == MatchReason.CROSS_SOURCE and pid == a.current_person_id:
                return False  # ré-affirmée à l'identique : pas d'écriture, pas d'ancrage, pas de compteur
        link_contribution(
            self._conn,
            pid,
            a.source,
            a.source_contribution_id,
            RESOLUTION_MODE_BY_REASON[reason],
        )
        # Identifiants ajoutés en `pending` quelle que soit la source du match.
        add_identifiers(pid, [a.identifiers], repo=self._repo)
        self._complete_first_name(pid, a)
        self.matched_counts[reason] += 1
        if not a.in_perimeter:
            self.out_of_perimeter_matched += 1
        # Un membre ferme (identifiant, nom, création) ancre le cross-source de son groupe ; un résultat cross-source, jamais — il n'ancre pas un autre cross-source.
        if a.group_id is not None and reason != MatchReason.CROSS_SOURCE:
            self._linked_index[a.group_id].append((pid, a.last_norm, a.first_norm, a.source))
        return True

    def apply_create(self, a: EnrichedContribution) -> None:
        if a.current_person_id is not None:
            # Ancienne contribution source cross-source qui rejoint une création : couverte ce run.
            self.resolved_cross_source_ids.add(a.source_contribution_id)
        last, first = validated_name(a.last_name or a.name.display(), a.first_name or "")
        marker = self._repo.create(last, first)
        link_contribution(
            self._conn,
            marker,
            a.source,
            a.source_contribution_id,
            "name",
        )
        add_identifiers(marker, [a.identifiers], repo=self._repo)
        self._index_namesake(Namesake(marker, last, first))
        # La personne créée ancre aussi le cross-source de son groupe, pour les autres contributions sources du même auteur.
        if a.group_id is not None:
            self._linked_index[a.group_id].append((marker, a.last_norm, a.first_norm, a.source))
        self.created += 1

    def _index_namesake(self, namesake: Namesake) -> None:
        """Rend la personne matchable dans la même passe par son nom de famille, et par les formes de son nom via le générateur qui sert au peuplement de `person_name_forms`.

        Les formes fusionnent dans les listes existantes : une forme déjà portée reste ambiguë (donc non matchée en aveugle), au lieu d'être détournée vers la dernière personne indexée.
        """
        previous = self._namesake_of.get(namesake.person_id)
        same_last_name = self._namesakes[normalize_text(namesake.last_name)]
        if previous is not None:
            same_last_name.remove(previous)
        same_last_name.append(namesake)
        self._namesake_of[namesake.person_id] = namesake
        for f in compute_person_name_forms(namesake.last_name, namesake.first_name):
            form_person_ids = self._name_form_map.setdefault(f, [])
            if namesake.person_id not in form_person_ids:
                form_person_ids.append(namesake.person_id)

    def _complete_first_name(self, pid: int, a: EnrichedContribution) -> None:
        """Donne à une personne au prénom réduit le prénom plein compatible de la contribution source qui la rejoint (« Tnourji A. » → « Tnourji Abdellah ») : une contribution source d'un autre prénom plein ne s'y rattache plus par ses initiales."""
        namesake = self._namesake_of.get(pid)
        if namesake is None or namesake.conflicting:
            return
        initials = first_name_initials(namesake.first_name)
        first_name = a.name.first_name_for(namesake.last_name)
        if (
            initials is None
            or first_name is None
            or not full_first_name_extends(initials, first_name)
        ):
            return
        self._repo.update_name(pid, *validated_name(namesake.last_name, first_name))
        self._index_namesake(namesake._replace(first_name=first_name))
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
    logger: logging.Logger,
    *,
    repo: PgPersonRepository,
    orphans_log: logging.Logger | None = None,
) -> CascadeResult:
    """Rattache les contributions sources aux personnes, en deux passes sur un **seul** `_Cascade` (index vivants partagés — un seul fetch, un seul chargement).

    Passe `match` (`decide_full`) : rattachement ferme (identifiant, nom) et cross-source contre les ancres présentes ; les contributions sources non rattachées sont reprises en passe suivante.

    `orphans_log` reçoit le motif de chaque contribution source du périmètre restée sans personne (`_Cascade.log_orphans`).

    Passe `create` (`decide_cross_and_name`) sur les seules contributions sources du périmètre restées sans personne : cross-source et nom contre l'état ferme complet, puis création des inconnues. Une création ancre le cross-source d'une autre contribution source du groupe traitée juste après, dans la même passe — sans quoi deux graphies du même auteur inconnu produiraient deux personnes.
    """
    etape(logger, "Identification des personnes")
    completion = complete_reduced_first_names(conn, repo=repo)
    logger.info(
        "%s%s d'après les contributions sources",
        BRANCHE,
        accord(completion.completed, "prénom complété", "prénoms complétés"),
    )
    # Le chargement des index précède tout affichage de volume : il dure, et la phase resterait
    # muette jusqu'à ce qu'il rende la main.
    with attente(f"{BRANCHE}chargement des contributions sources", logger) as ligne:
        c = _Cascade(
            conn,
            repo=repo,
            conflicting=completion.conflicting,
        )
        c.first_names_completed = completion.completed
        total = len(c.contributions)
        ligne.conclut(
            f"{BRANCHE}{accord(total, 'contribution source', 'contributions sources')} à examiner"
        )

    unresolved: list[EnrichedContribution] = []
    with progression(total, BRANCHE.rstrip(), logger, compte_retenus=True) as avancement:
        for a in c.contributions:
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

    # Seules les contributions sources du périmètre encore sans personne peuvent en créer une. Les autres —
    # hors périmètre, ou déjà liées en cross-source — n'attendent de cette passe qu'un
    # rattachement à une personne qu'elle vient de créer ; la passe suivante du run d'après les
    # rejuge contre l'état ferme complet.
    sans_personne = [a for a in unresolved if a.in_perimeter and a.current_person_id is None]
    non_identifiees = [a for a in sans_personne if a.allow_create]
    # Une création ajoute des personnes aux formes de nom sans en retirer : une forme indécidable le reste.
    indecidables = [a for a in non_identifiees if c.name_form_undecidable(a)]
    indecidables_ids = {a.source_contribution_id for a in indecidables}
    # Les contributions sources au nom séparé par la source passent en tête : la personne créée prend leur découpage plutôt que celui du parseur, et les graphies brutes la rejoignent ensuite.
    a_creer = sorted(
        (a for a in non_identifiees if a.source_contribution_id not in indecidables_ids),
        key=lambda a: not a.name.split_by_source,
    )

    etape(logger, "Création de nouvelles personnes")
    logger.info(
        "%s%s %s",
        BRANCHE,
        accord(len(non_identifiees), "contribution source", "contributions sources"),
        forme(len(non_identifiees), "non identifiée"),
    )
    logger.info(
        "%s%s (forme de nom ambiguë, ou candidats tous rejetés)",
        BRANCHE,
        accord(len(indecidables), "indécidable"),
    )
    creees_avant = c.created
    with progression(len(a_creer), BRANCHE.rstrip(), logger, compte_retenus=True) as avancement:
        for a in a_creer:
            avancement.avance()
            if c.resolve_or_create(a):
                avancement.retient()
    # Les contributions sources qui ne peuvent pas créer de personne — rôle exclu, forme de nom ambiguë —
    # peuvent encore rejoindre en cross-source une personne créée pour une autre contribution source du groupe. Traitées
    # après toutes les créations, elles en reçoivent tous les ancrages.
    for a in [*(a for a in sans_personne if not a.allow_create), *indecidables]:
        c.resolve_or_create(a)
    logger.info(
        "%s%s %s",
        DERNIERE_BRANCHE,
        accord(c.created - creees_avant, "personne"),
        forme(c.created - creees_avant, "créée"),
    )
    if orphans_log is not None:
        c.log_orphans(orphans_log)
    return c.result()
