"""
Crée des entités Personnes à partir des authorships sources non rattachées.

Deux populations de candidats traversent la **même** cascade :

- **In-périmètre** (`source_authorships.in_perimeter = TRUE`) : authorships dont
  la source a détecté une affiliation UCA. Éligibles à tous les barreaux.
- **Hors-périmètre** ancrés (`in_perimeter = FALSE`) : authorships rattachables
  sans forme de nom — identifiant fort partagé avec une personne connue, ou
  ancrage cross-source (même publication × position qu'un authorship déjà lié).
  Le barreau `person_name_forms` (match unique / création) y est neutralisé :
  un nom seul ne peut ni introduire ni attacher une personne hors-périmètre.
  Cf. `get_out_of_perimeter_candidates` et la garde dans la boucle.

La garde `in_perimeter` conditionne donc le seul barreau nominal : enregistrer
ce qu'une personne confirmée-par-identifiant a signé (link, name form,
identifiants) n'en dépend pas.

Cascade unifiée — une seule boucle qui interroge 5 signaux en parallèle puis
délègue la décision à `domain.persons.matching.decide_person_match`, du plus
fiable au moins fiable :

1. **ORCID** présent en base (status != rejected), utilisé comme signal
   uniquement quand l'authorship vient d'une source à ORCID déposé par
   l'auteur (`ORCID_MATCH_SOURCES` : crossref / openalex / hal). L'ORCID WoS,
   attribué algorithmiquement, n'est pas un signal de matching.
2. **`hal_person_id`** présent en base (status != rejected) — compte HAL,
   porté uniquement par les authorships HAL.
3. **IdRef** présent en base (status != rejected).
4. **Cross-source** par `(publication_id, author_position)` avec nom
   compatible — après les identifiants (inopérant au bootstrap).
5. **Lookup `person_name_forms`** : match unique / ambigu (skip) /
   inconnu (création si `allow_create`, skip sinon).

Garde de rejet : les personnes rejetées pour la publication (store
`rejected_authorships`, préfetché par publication) sont éliminées des
candidats à chaque signal — un match ne peut pas recréer une paire
rejetée, et l'élimination peut désambiguïser un name form (2 candidats
dont 1 rejeté → match univoque).

L'effet est appliqué selon l'action de la décision :
- Match (orcid / hal_person_id / idref / cross-source / name_form) → `link + add_name_form
  + add_identifiers`. Les identifiants sont ajoutés en statut `pending`
  (cf. `application.persons.add_identifier`), vérifiables manuellement
  via l'admin si le matching par nom s'avère faux. Cohérent avec le
  bootstrap d'une base vide : sans cet ajout, aucun identifier ne
  serait jamais inséré quand la même personne arrive depuis plusieurs
  sources successivement.
- Création → `create + link + add_identifiers + add_name_form`.
- Skip → rien (ambiguïté ou création interdite, cf. `allow_person_creation`).

L'orchestrateur dépend du port `PersonsCreateQueries`. Le point d'entrée CLI
est dans `interfaces/cli/pipeline/create_persons_from_source_authorships.py`.
"""

import logging
from collections import defaultdict
from typing import NamedTuple

from sqlalchemy import Connection

from application.persons.core import (
    IdentifierConflict,
    add_identifiers_from_authorships as add_identifiers,
    add_name_form,
    create_person,
    link_authorships as link_to_person,
)
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.persons.resolve_identifier_transfers import resolve_identifier_transfers
from application.ports.pipeline.persons_create import (
    BareUnlinkedAuthorship,
    PersonsCreateQueries,
)
from application.ports.repositories.person_repository import PersonRepository
from domain.normalize import normalize_name
from domain.persons.creation import allow_person_creation
from domain.persons.matching import (
    ORCID_MATCH_SOURCES,
    RESOLUTION_MODE_BY_REASON,
    NameFormDecision,
    decide_cross_source_match,
    decide_match_by_identifier,
    decide_name_form_outcome,
    decide_person_match,
)
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.name_matching import parse_raw_author_name


class EnrichedAuthorship(NamedTuple):
    """`BareUnlinkedAuthorship` enrichie côté Python : nom parsé, normalisations, flag de création autorisée."""

    authorship_id: int
    source: str
    full_name: str
    author_name_normalized: str | None
    orcid: str | None
    hal_person_id: str | None
    idref: str | None
    roles: list[str] | None
    publication_id: int | None
    author_position: int
    in_perimeter: bool
    last_name: str
    first_name: str
    last_norm: str
    first_norm: str
    allow_create: bool


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _enrich(row: BareUnlinkedAuthorship) -> EnrichedAuthorship:
    """Parse le nom, normalise, calcule le flag de création autorisée."""
    last_name, first_name = parse_raw_author_name(row.full_name)
    last_norm = normalize_name(last_name)
    first_norm = normalize_name(first_name)
    allow_create = allow_person_creation(row.source, row.roles or [])

    return EnrichedAuthorship(
        authorship_id=row.authorship_id,
        source=row.source,
        full_name=row.full_name,
        author_name_normalized=row.author_name_normalized,
        orcid=row.orcid,
        hal_person_id=row.hal_person_id,
        idref=row.idref,
        roles=row.roles,
        publication_id=row.publication_id,
        author_position=row.author_position,
        in_perimeter=row.in_perimeter,
        last_name=last_name,
        first_name=first_name,
        last_norm=last_norm,
        first_norm=first_norm,
        allow_create=allow_create,
    )


def get_all_unlinked_authorships(
    conn: Connection, queries: PersonsCreateQueries
) -> list[EnrichedAuthorship]:
    """Charge les authorships UCA sans person_id (toutes sources) et les enrichit
    (parsing noms, flag allow_create)."""
    return [_enrich(row) for row in queries.fetch_unlinked_authorships(conn)]


def get_out_of_perimeter_candidates(
    conn: Connection, queries: PersonsCreateQueries
) -> list[EnrichedAuthorship]:
    """Charge les candidats hors-périmètre rattachables sans forme de nom
    (identifiant fort partagé ou ancrage cross-source) et les enrichit.

    Ces candidats traversent la même cascade que les UCA, mais le barreau
    `person_name_forms` (match unique / création) y est neutralisé : un nom
    seul ne peut ni introduire ni attacher une personne hors-périmètre."""
    return [_enrich(row) for row in queries.fetch_out_of_perimeter_candidates(conn)]


def load_linked_authorships_by_pub(
    conn: Connection, queries: PersonsCreateQueries
) -> dict[tuple[int, int], list[tuple[int, str, str, str]]]:
    """Index des authorships rattachées par (publication_id, author_position)."""
    index: dict[tuple[int, int], list[tuple[int, str, str, str]]] = defaultdict(list)

    for r in queries.fetch_linked_authorships(conn):
        last, first = parse_raw_author_name(r.full_name)
        ln, fn = normalize_name(last), normalize_name(first)
        index[(r.publication_id, r.author_position)].append((r.person_id, ln, fn, r.source))

    return index


def _max_authors_per_pub(
    all_authorships: list[EnrichedAuthorship],
    linked_index: dict[tuple[int, int], list[tuple[int, str, str, str]]],
) -> dict[int, int]:
    """Nombre d'auteurs pour chaque publication (max parmi les sources).

    Sert au court-circuit du matching cross-source au-delà de
    `MAX_AUTHORS_CROSS_SOURCE`. Le matching personnes "cross-source" repose sur le
    triplet "même publi récupérée sur plusieurs sources, même position auteur, noms compatibles". Sur les méga-papers, ce triplet cesse d'être discriminant : désalignements de positions fréquents entre sources, homonymes de patronyme, prénoms réduits à l'initiale. Le seuil 50 est un proxy arbitraire pour écarter ces publis.

    Une publi peut avoir un nombre d'auteurs différent selon
    la source — il faut bien retenir un chiffre pour comparer au
    seuil. On prend le plus élevé par défensivité : si HAL dit 48 et
    OpenAlex 52, on est dans le régime méga-paper.
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
# Orchestrateur
# ---------------------------------------------------------------------------


def run(
    conn: Connection,
    queries: PersonsCreateQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
    dry_run: bool = False,
) -> PhaseMetrics:
    # Réinitialisation nominale (canal ordre-indépendant), avant de recharger les
    # non-rattachées : une signature dont la forme de nom est devenue ambiguë repasse
    # à NULL et repart dans la cascade. La personne réduite ainsi vidée est supprimée
    # après la boucle (GC), ce qui désambiguïse sa forme au run suivant.
    reorphaned = 0
    if not dry_run:
        reorphaned = queries.reorphan_ambiguous_nominal(conn)
        if reorphaned:
            logger.info(
                "Re-orphelinage nominal : %d signatures à forme ambiguë détachées", reorphaned
            )

    in_perimeter_authorships = get_all_unlinked_authorships(conn, queries)
    out_of_perimeter_authorships = get_out_of_perimeter_candidates(conn, queries)
    all_authorships = in_perimeter_authorships + out_of_perimeter_authorships
    logger.info(
        f"{len(in_perimeter_authorships)} authorships du périmètre non rattachées "
        f"+ {len(out_of_perimeter_authorships)} candidats hors-périmètre "
        f"(identifiant fort / cross-source)"
    )

    if not all_authorships:
        logger.info("Rien à faire.")
        return PhaseMetrics()

    # Prefetch global des 4 lookups (1 round-trip chacun, partagés sur toute la boucle).
    logger.info("Prefetch des lookups...")
    linked_index = load_linked_authorships_by_pub(conn, queries)
    idref_map = queries.fetch_idref_to_person_map(conn)
    orcid_map = queries.fetch_orcid_to_person_map(conn)
    hal_account_map = queries.fetch_hal_account_to_person_map(conn)
    name_form_map = queries.fetch_name_form_map(conn)
    name_form_status = queries.fetch_name_form_status_map(conn)
    rejected_by_pub = queries.fetch_rejected_person_ids_by_pub(conn)
    pub_max_authors = _max_authors_per_pub(all_authorships, linked_index)

    matched_counts: dict[str, int] = defaultdict(int)
    skipped_counts: dict[str, int] = defaultdict(int)
    created = 0
    out_of_perimeter_matched = 0
    corroboration_rejected = 0
    conflicts: list[IdentifierConflict] = []

    total = len(all_authorships)
    for i, a in enumerate(all_authorships):
        if i and i % 5000 == 0:
            logger.info("  %d/%d authorships traitées...", i, total)

        # ── Sous-décisions ─────────────────────────────────────────
        cross_source_match: int | None = None
        pub_id = a.publication_id
        position = a.author_position
        if pub_id is not None:
            candidates = linked_index.get((pub_id, position), [])
            if candidates:
                cross_source_match = decide_cross_source_match(
                    authorship_source=a.source,
                    last_norm=a.last_norm,
                    first_norm=a.first_norm,
                    candidates=candidates,
                    total_author_count=pub_max_authors.get(pub_id),
                )

        # Résolution corroborée par le nom : un match identifiant dont le nom de la
        # personne ciblée est incompatible avec la signature est refusé (corruption
        # éparse — un identifiant recopié sur le mauvais co-auteur) et journalisé.
        form = a.author_name_normalized
        idref_decision = decide_match_by_identifier(
            a.idref, idref_map, a.full_name, form, name_form_status
        )
        hal_decision = decide_match_by_identifier(
            a.hal_person_id, hal_account_map, a.full_name, form, name_form_status
        )
        # ORCID utilisé comme signal de matching uniquement quand il est
        # déposé par l'auteur (crossref / openalex raw_orcid / hal TEI) ;
        # l'ORCID WoS, attribué algorithmiquement, est ignoré ici (il reste
        # enregistré sur person_identifiers via add_identifiers).
        orcid_signal = a.orcid if a.source in ORCID_MATCH_SOURCES else None
        orcid_decision = decide_match_by_identifier(
            orcid_signal, orcid_map, a.full_name, form, name_form_status
        )

        for id_type, id_value, id_decision in (
            ("orcid", orcid_signal, orcid_decision),
            ("hal_person_id", a.hal_person_id, hal_decision),
            ("idref", a.idref, idref_decision),
        ):
            if id_decision.rejection is not None:
                rejected_pid, target_name = id_decision.rejection
                logger.info(
                    "corroboration: rejet %s=%s — signature %r incompatible avec personne %d (%r)",
                    id_type,
                    id_value,
                    a.full_name,
                    rejected_pid,
                    target_name,
                )
                corroboration_rejected += 1

        idref_match = idref_decision.person_id
        hal_match = hal_decision.person_id
        orcid_match = orcid_decision.person_id

        # Garde de rejet : personnes rejetées pour cette publication, à
        # éliminer des candidats (matchs annulés, name form désambiguïsé).
        rejected_for_pub = (
            rejected_by_pub.get(pub_id, frozenset()) if pub_id is not None else frozenset()
        )

        # Barreau name_form réservé au périmètre UCA : hors-périmètre, un nom
        # seul ne peut ni attacher ni créer une personne (on n'a que des
        # candidats ancrés sur un identifiant fort ou une position cross-source).
        if a.in_perimeter:
            norm = a.author_name_normalized
            name_form_outcome = decide_name_form_outcome(
                name_form_map.get(norm) if norm else None,
                a.allow_create,
                rejected_person_ids=rejected_for_pub,
            )
        else:
            name_form_outcome = NameFormDecision(action="skip", reason="out_of_perimeter")

        # ── Décision unifiée ────────────────────────────────────────
        decision = decide_person_match(
            orcid_match=orcid_match,
            hal_match=hal_match,
            idref_match=idref_match,
            cross_source_match=cross_source_match,
            name_form_outcome=name_form_outcome,
            rejected_person_ids=rejected_for_pub,
        )

        # ── Effets ─────────────────────────────────────────────────
        if decision.action == "match":
            pid = decision.person_id
            assert pid is not None  # garanti par decide_person_match action=match
            if not dry_run:
                # `link_to_person` et `add_identifiers` consomment des dicts (API
                # historique de `application.persons`) : on convertit l'EnrichedAuthorship
                # via `_asdict()` au boundary. Le typage strict reste interne au pipeline.
                a_dict = a._asdict()
                link_to_person(
                    pid,
                    [a_dict],
                    repo=person_repo,
                    resolution_mode=RESOLUTION_MODE_BY_REASON[decision.reason],
                )
                add_name_form(pid, a.full_name, repo=person_repo)
                # Identifiants ajoutés en statut `pending` quelle que soit la
                # source du match (cross-source/idref/orcid/name_form) —
                # vérifiables manuellement via l'admin si erronés.
                add_identifiers(pid, [a_dict], repo=person_repo, conflicts=conflicts)
            matched_counts[decision.reason] += 1
            if not a.in_perimeter:
                out_of_perimeter_matched += 1
            # Mettre à jour linked_index pour que les authorships suivantes
            # sur la même (pub_id, position) puissent matcher en cross-source.
            if pub_id is not None:
                linked_index[(pub_id, position)].append((pid, a.last_norm, a.first_norm, a.source))

        elif decision.action == "create":
            last = a.last_name or a.full_name or "?"
            first = a.first_name or ""
            if not dry_run:
                pid = create_person(last, first, repo=person_repo)
                a_dict = a._asdict()
                link_to_person(pid, [a_dict], repo=person_repo, resolution_mode="name")
                add_identifiers(pid, [a_dict], repo=person_repo, conflicts=conflicts)
                add_name_form(pid, a.full_name, repo=person_repo)
                marker = pid
            else:
                marker = -1
            # Rendre la personne créée matchable dans le même run par toutes ses
            # formes — ordres ET initiales — via le générateur qui sert au
            # peuplement de `person_name_forms`, plutôt que les deux seuls ordres.
            # Sans les initiales, une signature « J Martin » du même run ne
            # rattrape pas la « Jean Martin » qu'on vient de créer. On fusionne
            # dans les listes de candidats existantes plutôt que d'écraser : une
            # forme déjà portée par d'autres personnes reste ambiguë (donc non
            # matchée en aveugle), au lieu d'être détournée vers la dernière créée.
            for form in compute_person_name_forms(last, first):
                form_person_ids = name_form_map.setdefault(form, [])
                if marker not in form_person_ids:
                    form_person_ids.append(marker)
            created += 1

        else:  # skip
            skipped_counts[decision.reason] += 1

    # ── Arbitrage des conflits d'attribution par consensus ─────────
    # Les valeurs d'identifiant captées par un premier arrivé sont transférées à la
    # personne que soutient la majorité des porteurs (cf. resolve_identifier_transfers).
    transferred = 0
    if not dry_run:
        transferred = resolve_identifier_transfers(
            conn, conflicts, queries=queries, repo=person_repo, logger=logger
        )["transferred"]

    # ── GC des personnes vidées ────────────────────────────────────
    # Une personne réduite dont les signatures ont été re-orphelinées (puis rejointes à
    # la forme pleine, ou laissées orphelines) n'a plus de signature : la supprimer retire
    # sa forme canonique et désambiguïse pour le run suivant.
    deleted_persons = 0
    if not dry_run:
        deleted_persons = queries.delete_empty_persons(conn)
        if deleted_persons:
            logger.info("GC : %d personnes vidées supprimées", deleted_persons)

    # ── Résumé ─────────────────────────────────────────────────────
    linked_total = sum(matched_counts.values())
    in_perimeter_total = len(in_perimeter_authorships)
    out_of_perimeter_total = len(out_of_perimeter_authorships)
    in_perimeter_matched = linked_total - out_of_perimeter_matched
    in_perimeter_unlinked = in_perimeter_total - in_perimeter_matched - created

    logger.info("\n=== Résumé ===")
    logger.info(f"  ORCID                    : {matched_counts['orcid']} rattachées")
    logger.info(f"  hal_person_id            : {matched_counts['hal_person_id']} rattachées")
    logger.info(f"  IdRef                    : {matched_counts['idref']} rattachées")
    logger.info(f"  Cross-source             : {matched_counts['cross_source']} rattachées")
    logger.info(f"  Name form (single match) : {matched_counts['single_name']} rattachées")
    logger.info(f"  Créées                   : {created}")
    logger.info(f"  Rejets corroboration nom : {corroboration_rejected} matchs identifiant refusés")
    logger.info(f"  Identifiants transférés  : {transferred} (conflit résolu par consensus)")
    logger.info(f"  Re-orphelinées (nominal) : {reorphaned} (forme devenue ambiguë)")
    logger.info(f"  Personnes vidées (GC)    : {deleted_persons}")
    logger.info(
        f"  Skippées (in-perimeter)  : ambiguës={skipped_counts['ambiguous_name_form']}, "
        f"create interdit={skipped_counts['creation_not_allowed']}"
    )
    logger.info(f"  Non résolues (in-perimeter): {in_perimeter_unlinked}")
    logger.info(
        f"  Hors-périmètre           : {out_of_perimeter_matched}/{out_of_perimeter_total} "
        f"candidats rattachés (identifiant fort / cross-source)"
    )
    # Commit/rollback laissés au caller (le CLI commit / rollback selon
    # `--dry-run`, les tests d'intégration restent dans leur transaction
    # rollbackée).

    metrics = PhaseMetrics()
    metrics.add(total=total, new=created, updated=linked_total)
    # Tableau « méthode de rattachement » : clés techniques (libellés portés par le
    # frontend), ordre par fiabilité décroissante de la cascade.
    metrics.details["table"] = {
        "rows": [
            {"key": method, "count": matched_counts[method]}
            for method in ("orcid", "hal_person_id", "idref", "cross_source", "single_name")
        ]
    }
    metrics.details["summary"] = {
        "created": created,
        "skipped_ambiguous": skipped_counts["ambiguous_name_form"],
        "corroboration_rejected": corroboration_rejected,
        "identifiers_transferred": transferred,
        "reorphaned_nominal": reorphaned,
        "deleted_empty_persons": deleted_persons,
    }
    return metrics
