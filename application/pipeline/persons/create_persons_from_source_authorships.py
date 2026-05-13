"""
Crée des entités Personnes à partir des authorships sources UCA non rattachées.

Algorithme en 4 étapes + 1 étape complémentaire :

  Étape 1 : Cross-source
    Pour chaque authorship sans person_id, chercher sur la même publication
    (même position) une authorship d'une autre source qui a un person_id.
    Si le nom est compatible → rattacher à cette personne.

  Étape 1b : IdRef connu
    Si l'authorship a un IdRef déjà présent en base (status != rejected)
    et mappé à une personne → rattacher à cette personne.

  Étape 2 : ORCID connu
    Si l'authorship a un ORCID déjà présent en base (status != rejected)
    et mappé à une personne → rattacher à cette personne.
    L'ORCID ne prime pas sur le cross-source (risque d'ORCID erroné
    dans OpenAlex/WoS supérieur au risque d'homonymie en cross-source).

  Étape 3 : Lookup person_name_forms
    Normaliser le nom de l'auteur et chercher dans person_name_forms.
    - Mappé à 1 personne → rattacher
    - Mappé à >1 personnes → orphelin (traitement manuel)
    - Forme inconnue → créer nouvelle personne

  Étape 4 : Presonnes liées aux thèses (directeurs, rapporteurs, jury)
    Les rôles non-auteur des thèses sont hors périmètre (in_perimeter=false: pas de signatures ni de structure_ids) et ne passent pas par les étapes 1-3. Si leur source_author a un IdRef correspondant à une personne connue, on rattache sans modifier in_perimeter ni créer de personne.

Note : un matching par idhal / hal_person_id sera réintroduit dans le
chantier `METIER_decide-person-match` (étape dédiée au côté du matching
par identifiants forts).

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
from application.ports.persons_create import PersonsCreateQueries
from domain.normalize import normalize_name
from domain.persons.creation import allow_person_creation
from domain.persons.matching import (
    decide_cross_source_match,
    decide_match_by_identifier,
    decide_name_form_outcome,
)
from domain.persons.name_matching import parse_raw_author_name
from domain.ports.person_repository import PersonRepository
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

        if r.get("oa_orcid"):
            r["orcid"] = keep_orcid_if_name_matches(
                raw_full_name=r["full_name"],
                oa_full_name=r.get("oa_full_name", ""),
                oa_orcid=r["oa_orcid"],
            )
            r.pop("oa_orcid", None)
            r.pop("oa_full_name", None)

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


# ---------------------------------------------------------------------------
# Étape 1 : Cross-source
# ---------------------------------------------------------------------------


def _max_authors_per_pub(
    all_authorships: Any,
    linked_index: dict,
) -> dict[int, int]:
    """Max d'auteurs sur une publication par source (linked + unlinked).

    Sur les méga-papers (consortiums), le matching cross-source par
    position est désactivé via `MAX_AUTHORS_CROSS_SOURCE` car les
    positions divergent trop entre sources. Pour appliquer ce seuil,
    on calcule pour chaque publi le max d'auteurs trouvés sur une
    même source — cohérent avec le filtre `MAX_AUTHORS_CONFLICT`
    côté admin (`infrastructure/db/queries/person_duplicates.py`).
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


def step1_cross_source(
    logger: logging.Logger,
    all_authorships: Any,
    linked_ids: set,
    linked_index: dict,
    dry_run: bool,
    *,
    person_repo: PersonRepository,
) -> int:
    """Match par (publication, position) avec nom compatible d'une autre source.

    Court-circuit sur les méga-papers (cf. `MAX_AUTHORS_CROSS_SOURCE`)
    où les positions divergent trop entre sources pour qu'un match par
    position soit fiable.
    """
    pub_max_authors = _max_authors_per_pub(all_authorships, linked_index)

    linked = 0
    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        pub_id = a["publication_id"]
        position = a["author_position"]
        if pub_id is None or position is None:
            continue

        candidates = linked_index.get((pub_id, position), [])
        if not candidates:
            continue

        matched_pid = decide_cross_source_match(
            authorship_source=a["source"],
            last_norm=a["last_norm"],
            first_norm=a["first_norm"],
            candidates=candidates,
            total_author_count=pub_max_authors.get(pub_id),
        )

        if matched_pid:
            if not dry_run:
                link_to_person(matched_pid, [a], repo=person_repo)
                add_name_form(matched_pid, a["full_name"], repo=person_repo)
                add_identifiers(matched_pid, [a], repo=person_repo)
            linked_ids.add((a["source"], a["authorship_id"]))
            ln, fn = a["last_norm"], a["first_norm"]
            linked_index[(pub_id, position)].append((matched_pid, ln, fn, a["source"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par cross-source")
    return linked


# ---------------------------------------------------------------------------
# Étape 1b : IdRef connu
# ---------------------------------------------------------------------------


def step1b_idref(
    conn: Connection,
    queries: PersonsCreateQueries,
    logger: logging.Logger,
    all_authorships: Any,
    linked_ids: set,
    dry_run: bool,
    *,
    person_repo: PersonRepository,
) -> int:
    """Si l'authorship a un IdRef déjà connu en base (non rejeté), rattacher."""
    idref_map = queries.fetch_idref_to_person_map(conn)
    linked = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        pid = decide_match_by_identifier(a.get("idref"), idref_map)
        if pid:
            if not dry_run:
                link_to_person(pid, [a], repo=person_repo)
                add_name_form(pid, a["full_name"], repo=person_repo)
                add_identifiers(pid, [a], repo=person_repo)
            linked_ids.add((a["source"], a["authorship_id"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par IdRef connu")
    return linked


# ---------------------------------------------------------------------------
# Étape 2 : ORCID connu
# ---------------------------------------------------------------------------


def step2_orcid(
    conn: Connection,
    queries: PersonsCreateQueries,
    logger: logging.Logger,
    all_authorships: Any,
    linked_ids: set,
    dry_run: bool,
    *,
    person_repo: PersonRepository,
) -> int:
    """Si l'authorship a un ORCID déjà connu en base, rattacher."""
    orcid_map = queries.fetch_orcid_to_person_map(conn)
    linked = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        pid = decide_match_by_identifier(a.get("orcid"), orcid_map)
        if pid:
            if not dry_run:
                link_to_person(pid, [a], repo=person_repo)
                add_name_form(pid, a["full_name"], repo=person_repo)
                add_identifiers(pid, [a], repo=person_repo)
            linked_ids.add((a["source"], a["authorship_id"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par ORCID connu")
    return linked


# ---------------------------------------------------------------------------
# Étape 3 : Lookup person_name_forms
# ---------------------------------------------------------------------------


def step3_name_forms(
    logger: logging.Logger,
    all_authorships: Any,
    linked_ids: set,
    name_form_map: dict,
    dry_run: bool,
    *,
    person_repo: PersonRepository,
) -> tuple[int, int, int]:
    """Lookup direct par `source_authorships.author_name_normalized` dans
    `person_name_forms`.

    Sémantique : la forme normalisée stockée à l'ingestion (via la fonction
    SQL `normalize_name_form`) est utilisée directement comme clé de
    lookup. La table `person_name_forms` contient déjà toutes les
    variantes (ordres prénom/nom, initiales) générées par
    `domain.names.compute_person_name_forms` à la création des personnes
    et alimentées par `populate_person_name_forms` pour les authorships
    rattachées — donc une seule clé de lookup suffit, n'importe laquelle
    des variantes matchera.
    """
    linked = 0
    created = 0
    skipped = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        norm = a.get("author_name_normalized")
        if not norm:
            continue

        decision = decide_name_form_outcome(name_form_map.get(norm), a.get("allow_create", True))

        if decision.action == "match":
            pid = decision.person_id
            assert pid is not None  # narrowing : garanti par decide_name_form_outcome
            if not dry_run:
                link_to_person(pid, [a], repo=person_repo)
                add_name_form(pid, a["full_name"], repo=person_repo)
            linked_ids.add((a["source"], a["authorship_id"]))
            linked += 1
        elif decision.action == "skip":
            skipped += 1
        else:  # create
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

            linked_ids.add((a["source"], a["authorship_id"]))
            created += 1

    logger.info(
        f"  {created} personnes créées, {linked} rattachées, {skipped} skippées (ambiguës ou création interdite)"
    )
    return created, linked, skipped


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

    linked_ids: set[tuple[str, int]] = set()

    logger.info("\n--- Étape 1 : cross-source (même publi + position) ---")
    linked_index = load_linked_authorships_by_pub(conn, queries)
    s1 = step1_cross_source(
        logger, all_authorships, linked_ids, linked_index, dry_run, person_repo=person_repo
    )

    logger.info("\n--- Étape 1b : IdRef connu ---")
    s1b = step1b_idref(
        conn, queries, logger, all_authorships, linked_ids, dry_run, person_repo=person_repo
    )

    logger.info("\n--- Étape 2 : ORCID connu ---")
    s2 = step2_orcid(
        conn, queries, logger, all_authorships, linked_ids, dry_run, person_repo=person_repo
    )

    logger.info("\n--- Étape 3 : person_name_forms ---")
    name_form_map = queries.fetch_name_form_map(conn)
    s3_created, s3_linked, s3_skipped = step3_name_forms(
        logger,
        all_authorships,
        linked_ids,
        name_form_map,
        dry_run,
        person_repo=person_repo,
    )

    total_linked = len(linked_ids)
    unlinked = len(all_authorships) - total_linked

    logger.info("\n=== Résumé ===")
    logger.info(f"  Étape 1 (cross-source)   : {s1} rattachées")
    logger.info(f"  Étape 1b (IdRef connu)   : {s1b} rattachées")
    logger.info(f"  Étape 2 (ORCID connu)    : {s2} rattachées")
    logger.info(
        f"  Étape 3 (name_forms)     : {s3_created} créées, {s3_linked} rattachées, "
        f"{s3_skipped} skippées"
    )
    logger.info(f"  Non résolues             : {unlinked}")

    if dry_run:
        conn.rollback()
        logger.info("\n  (dry-run — rien n'a été modifié)")
    else:
        conn.commit()
        logger.info("\n  ✓ Appliqué.")
        logger.info("  → Lancer build_authorships.py pour propager in_perimeter/structure_ids")
