"""
Crée des entités Personnes à partir des authorships sources UCA non rattachées.

Cascade unifiée — une seule boucle qui interroge 4 signaux en parallèle puis
délègue la décision à `domain.persons.matching.decide_person_match` :

1. **Cross-source** par `(publication_id, author_position)` avec nom compatible.
2. **IdRef** présent en base (status != rejected).
3. **ORCID** présent en base (status != rejected).
4. **Lookup `person_name_forms`** : match unique / ambigu (skip) /
   inconnu (création si `allow_create`, skip sinon).

L'effet est appliqué selon l'action de la décision :
- Match (cross-source / idref / orcid / name_form) → `link + add_name_form
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
from typing import Any

from sqlalchemy import Connection

from application.persons import (
    add_identifiers_from_authorships as add_identifiers,
)
from application.persons import (
    add_name_form,
    create_person,
)
from application.persons import (
    link_authorships as link_to_person,
)
from application.ports.pipeline.persons_create import PersonsCreateQueries
from application.ports.repositories.person_repository import PersonRepository
from domain.normalize import normalize_name
from domain.persons.creation import allow_person_creation
from domain.persons.matching import (
    decide_cross_source_match,
    decide_match_by_identifier,
    decide_name_form_outcome,
    decide_person_match,
)
from domain.persons.name_matching import parse_raw_author_name
from domain.sources.openalex import keep_orcid_if_name_matches

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def get_all_unlinked_authorships(
    conn: Connection, queries: PersonsCreateQueries
) -> list[dict[str, Any]]:
    """Charge les authorships UCA sans person_id (toutes sources) et les enrichit
    (parsing noms, filtrage ORCID OpenAlex, flag allow_create)."""
    all_rows = []
    for r in queries.fetch_unlinked_authorships(conn):
        r["last_name"], r["first_name"] = parse_raw_author_name(r["full_name"])
        r["last_norm"] = normalize_name(r["last_name"])
        r["first_norm"] = normalize_name(r["first_name"])

        r["allow_create"] = allow_person_creation(r["source"], r.get("roles") or [])

        # OpenAlex assigne à chaque authorship une entité auteur de son
        # référentiel ; cette assignation peut être fautive, et l'ORCID
        # rattaché à l'entité auteur peut alors être celui d'une autre
        # personne. On confronte le nom de l'entité auteur OA
        # (`oa_display_name`) au `raw_author_name` de la signature : si
        # incompatibles ou si `display_name` est absent, on drop l'ORCID.
        # Les autres sources fournissent un ORCID lié directement à la
        # signature, pas de filtre nécessaire.
        if r["source"] == "openalex" and r.get("orcid"):
            r["orcid"] = keep_orcid_if_name_matches(
                raw_full_name=r["full_name"],
                oa_full_name=r.get("oa_display_name"),
                oa_orcid=r["orcid"],
            )
        r.pop("oa_display_name", None)

        all_rows.append(r)

    return all_rows


def load_linked_authorships_by_pub(
    conn: Connection, queries: PersonsCreateQueries
) -> dict[tuple[int, int], list[tuple[int, str, str, str]]]:
    """Index des authorships rattachées par (publication_id, author_position)."""
    index: dict[tuple[int, int], list[tuple[int, str, str, str]]] = defaultdict(list)

    for r in queries.fetch_linked_authorships(conn):
        last, first = parse_raw_author_name(r["full_name"])
        ln, fn = normalize_name(last), normalize_name(first)
        index[(r["publication_id"], r["author_position"])].append(
            (r["person_id"], ln, fn, r["source"])
        )

    return index


def _max_authors_per_pub(
    all_authorships: list[dict[str, Any]],
    linked_index: dict[tuple[int, int], list[tuple[int, str, str, str]]],
) -> dict[int, int]:
    """Max d'auteurs sur une publication par source (linked + unlinked).

    Sur les méga-papers (consortiums), le matching cross-source par
    position est désactivé via `MAX_AUTHORS_CROSS_SOURCE` car les
    positions divergent trop entre sources. Pour appliquer ce seuil,
    on calcule pour chaque publi le max d'auteurs trouvés sur une
    même source — cohérent avec le filtre `MAX_AUTHORS_CONFLICT`
    côté admin (`infrastructure/queries/person_duplicates.py`).
    """
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for a in all_authorships:
        pub_id = a.get("publication_id")
        if pub_id is None:
            continue
        counts[pub_id][a["source"]] += 1
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
) -> None:
    all_authorships = get_all_unlinked_authorships(conn, queries)
    logger.info(f"{len(all_authorships)} authorships UCA non rattachées (toutes sources)")

    if not all_authorships:
        logger.info("Rien à faire.")
        return

    # Prefetch global des 4 lookups (1 round-trip chacun, partagés sur toute la boucle).
    logger.info("Prefetch des lookups...")
    linked_index = load_linked_authorships_by_pub(conn, queries)
    idref_map = queries.fetch_idref_to_person_map(conn)
    orcid_map = queries.fetch_orcid_to_person_map(conn)
    name_form_map = queries.fetch_name_form_map(conn)
    pub_max_authors = _max_authors_per_pub(all_authorships, linked_index)

    matched_counts: dict[str, int] = defaultdict(int)
    skipped_counts: dict[str, int] = defaultdict(int)
    created = 0

    for a in all_authorships:
        # ── Sous-décisions ─────────────────────────────────────────
        cross_source_match: int | None = None
        pub_id = a["publication_id"]
        position = a["author_position"]
        if pub_id is not None and position is not None:
            candidates = linked_index.get((pub_id, position), [])
            if candidates:
                cross_source_match = decide_cross_source_match(
                    authorship_source=a["source"],
                    last_norm=a["last_norm"],
                    first_norm=a["first_norm"],
                    candidates=candidates,
                    total_author_count=pub_max_authors.get(pub_id),
                )

        idref_match = decide_match_by_identifier(a.get("idref"), idref_map)
        orcid_match = decide_match_by_identifier(a.get("orcid"), orcid_map)

        norm = a.get("author_name_normalized")
        name_form_outcome = decide_name_form_outcome(
            name_form_map.get(norm) if norm else None,
            a.get("allow_create", True),
        )

        # ── Décision unifiée ────────────────────────────────────────
        decision = decide_person_match(
            cross_source_match=cross_source_match,
            idref_match=idref_match,
            orcid_match=orcid_match,
            name_form_outcome=name_form_outcome,
        )

        # ── Effets ─────────────────────────────────────────────────
        if decision.action == "match":
            pid = decision.person_id
            assert pid is not None  # garanti par decide_person_match action=match
            if not dry_run:
                link_to_person(pid, [a], repo=person_repo)
                add_name_form(pid, a["full_name"], repo=person_repo)
                # Identifiants ajoutés en statut `pending` quelle que soit la
                # source du match (cross-source/idref/orcid/name_form) —
                # vérifiables manuellement via l'admin si erronés.
                add_identifiers(pid, [a], repo=person_repo)
            matched_counts[decision.reason] += 1
            # Mettre à jour linked_index pour que les authorships suivantes
            # sur la même (pub_id, position) puissent matcher en cross-source.
            if pub_id is not None and position is not None:
                ln, fn = a["last_norm"], a["first_norm"]
                linked_index[(pub_id, position)].append((pid, ln, fn, a["source"]))

        elif decision.action == "create":
            last = a["last_name"] or a["full_name"] or "?"
            first = a["first_name"] or ""
            # On pré-popule la map en mémoire avec les deux ordres normalisés
            # pour qu'une autre authorship du même run avec l'ordre inverse
            # match cette personne nouvellement créée. La forme déjà
            # cherchée (norm) est forcément l'un des deux ordres.
            ln, fn = a["last_norm"], a["first_norm"]
            cache_forms = [f for f in [f"{fn} {ln}".strip(), f"{ln} {fn}".strip()] if f]
            if not dry_run:
                pid = create_person(last, first, repo=person_repo)
                link_to_person(pid, [a], repo=person_repo)
                add_identifiers(pid, [a], repo=person_repo)
                add_name_form(pid, a["full_name"], repo=person_repo)
                for form in cache_forms:
                    name_form_map[form] = [pid]
            else:
                for form in cache_forms:
                    name_form_map[form] = [-1]
            created += 1

        else:  # skip
            skipped_counts[decision.reason] += 1

    # ── Résumé ─────────────────────────────────────────────────────
    linked_total = sum(matched_counts.values())
    skipped_total = sum(skipped_counts.values())
    unlinked = len(all_authorships) - linked_total - created

    logger.info("\n=== Résumé ===")
    logger.info(f"  Cross-source             : {matched_counts['cross_source']} rattachées")
    logger.info(f"  IdRef                    : {matched_counts['idref']} rattachées")
    logger.info(f"  ORCID                    : {matched_counts['orcid']} rattachées")
    logger.info(f"  Name form (single match) : {matched_counts['single_name']} rattachées")
    logger.info(f"  Créées                   : {created}")
    logger.info(
        f"  Skippées                 : {skipped_total} "
        f"(ambiguës={skipped_counts['ambiguous_name_form']}, "
        f"create interdit={skipped_counts['creation_not_allowed']})"
    )
    logger.info(f"  Non résolues             : {unlinked}")
    # Commit/rollback laissés au caller (le CLI commit / rollback selon
    # `--dry-run`, les tests d'intégration restent dans leur transaction
    # rollbackée).
