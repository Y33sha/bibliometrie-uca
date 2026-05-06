"""
Crée des entités Personnes à partir des authorships sources UCA non rattachées.

Algorithme en 4 étapes + 1 étape complémentaire :

  Étape 0 : Comptes HAL déjà rattachés
    source_persons HAL avec hal_person_id ET person_id → propagation aux nouvelles
    authorships du même compte. Les comptes non rattachés sont laissés
    aux étapes suivantes (matching par nom, ORCID, position).

  Étape 1 : Cross-source
    Pour chaque authorship sans person_id, chercher sur la même publication
    (même position) une authorship d'une autre source qui a un person_id.
    Si le nom est compatible → rattacher à cette personne.

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
    Les rôles non-auteur des thèses sont hors périmètre (in_perimeter=false: pas de signatures ni de structure_ids) et ne passent pas par les étapes 0-3. Si leur source_author a un IdRef correspondant à une personne connue, on rattache sans modifier in_perimeter ni créer de personne.

L'orchestrateur dépend du port `PersonsCreateQueries`. Le point d'entrée CLI
est dans `interfaces/cli/pipeline/create_persons_from_source_authorships.py`.
"""

from collections import defaultdict
from typing import Any

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
from domain.names import names_compatible, parse_raw_author_name
from domain.normalize import normalize_name
from domain.ports.person_repository import PersonRepository

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def get_all_unlinked_authorships(cur: Any, queries: PersonsCreateQueries) -> list[dict[str, Any]]:
    """Charge les authorships UCA sans person_id (toutes sources) et les enrichit
    (parsing noms, filtrage ORCID OpenAlex, flag allow_create)."""
    all_rows = []
    for r in queries.fetch_unlinked_authorships(cur):
        r["last_name"], r["first_name"] = parse_raw_author_name(r["full_name"])
        r["last_norm"] = normalize_name(r["last_name"])
        r["first_norm"] = normalize_name(r["first_name"])

        # Les rôles non-auteur des thèses ne créent pas de personne
        roles = r.get("roles") or []
        r["allow_create"] = not (r["source"] == "theses" and "author" not in roles)

        # ORCID OpenAlex : ne garder que si le nom de l'entité auteur OA
        # est compatible avec le raw_author_name de l'authorship
        if r.get("oa_orcid"):
            oa_ln, oa_fn = parse_raw_author_name(r.get("oa_full_name", ""))
            if names_compatible(
                r["last_norm"], r["first_norm"], normalize_name(oa_ln), normalize_name(oa_fn)
            ):
                r["orcid"] = r["oa_orcid"]
            else:
                r["orcid"] = None
            r.pop("oa_orcid", None)
            r.pop("oa_full_name", None)

        all_rows.append(r)

    return all_rows


def load_linked_authorships_by_pub(
    cur: Any, queries: PersonsCreateQueries
) -> dict[tuple[int, int], list[tuple[int, str, str, str]]]:
    """Index des authorships rattachées par (publication_id, author_position)."""
    index: dict[tuple[int, int], list[tuple[int, str, str, str]]] = defaultdict(list)

    for r in queries.fetch_linked_authorships(cur):
        last, first = parse_raw_author_name(r["full_name"])
        ln, fn = normalize_name(last), normalize_name(first)
        index[(r["publication_id"], r["author_position"])].append(
            (r["person_id"], ln, fn, r["source"])
        )

    return index


# ---------------------------------------------------------------------------
# Étape 0 : Comptes HAL
# ---------------------------------------------------------------------------


def step0_hal_accounts(
    cur: Any,
    queries: PersonsCreateQueries,
    logger: Any,
    all_authorships: Any,
    linked_ids: set,
    dry_run: bool,
    *,
    person_repo: PersonRepository,
) -> int:
    """Propagation des comptes HAL déjà rattachés à une personne."""
    by_hal_pid = defaultdict(list)
    for a in all_authorships:
        if a["source"] == "hal" and a["has_hal_person_id"]:
            by_hal_pid[a["hal_person_id"]].append(a)

    hal_person_map = queries.fetch_hal_account_to_person_map(cur)

    linked = 0
    skipped = 0
    for hal_pid, group in by_hal_pid.items():
        existing_pid = hal_person_map.get(hal_pid)
        if existing_pid:
            if not dry_run:
                link_to_person(cur, existing_pid, group, repo=person_repo)
                add_identifiers(cur, existing_pid, group, repo=person_repo)
            linked += len(group)
            for a in group:
                linked_ids.add((a["source"], a["authorship_id"]))
        else:
            skipped += len(group)

    logger.info(
        f"  {linked} authorships rattachées, {skipped} ignorées (comptes HAL non rattachés)"
    )
    return linked


# ---------------------------------------------------------------------------
# Étape 1 : Cross-source
# ---------------------------------------------------------------------------


def step1_cross_source(
    cur: Any,
    logger: Any,
    all_authorships: Any,
    linked_ids: set,
    linked_index: dict,
    dry_run: bool,
    *,
    person_repo: PersonRepository,
) -> int:
    """Match par (publication, position) avec nom compatible d'une autre source."""
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

        matched_pid = None
        for pid, ln, fn, src in candidates:
            if src == a["source"]:
                continue
            if names_compatible(a["last_norm"], a["first_norm"], ln, fn):
                if matched_pid is not None and matched_pid != pid:
                    matched_pid = None
                    break
                matched_pid = pid

        if matched_pid:
            if not dry_run:
                link_to_person(cur, matched_pid, [a], repo=person_repo)
                add_name_form(cur, matched_pid, a["full_name"], repo=person_repo)
                add_identifiers(cur, matched_pid, [a], repo=person_repo)
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
    cur: Any,
    queries: PersonsCreateQueries,
    logger: Any,
    all_authorships: Any,
    linked_ids: set,
    dry_run: bool,
    *,
    person_repo: PersonRepository,
) -> int:
    """Si l'authorship a un IdRef déjà connu en base (non rejeté), rattacher."""
    idref_map = queries.fetch_idref_to_person_map(cur)
    linked = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        idref = a.get("idref")
        if not idref:
            continue

        pid = idref_map.get(idref)
        if pid:
            if not dry_run:
                link_to_person(cur, pid, [a], repo=person_repo)
                add_name_form(cur, pid, a["full_name"], repo=person_repo)
                add_identifiers(cur, pid, [a], repo=person_repo)
            linked_ids.add((a["source"], a["authorship_id"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par IdRef connu")
    return linked


# ---------------------------------------------------------------------------
# Étape 2 : ORCID connu
# ---------------------------------------------------------------------------


def step2_orcid(
    cur: Any,
    queries: PersonsCreateQueries,
    logger: Any,
    all_authorships: Any,
    linked_ids: set,
    dry_run: bool,
    *,
    person_repo: PersonRepository,
) -> int:
    """Si l'authorship a un ORCID déjà connu en base, rattacher."""
    orcid_map = queries.fetch_orcid_to_person_map(cur)
    linked = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        orcid = a.get("orcid")
        if not orcid:
            continue

        pid = orcid_map.get(orcid)
        if pid:
            if not dry_run:
                link_to_person(cur, pid, [a], repo=person_repo)
                add_name_form(cur, pid, a["full_name"], repo=person_repo)
                add_identifiers(cur, pid, [a], repo=person_repo)
            linked_ids.add((a["source"], a["authorship_id"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par ORCID connu")
    return linked


# ---------------------------------------------------------------------------
# Étape 3 : Lookup person_name_forms
# ---------------------------------------------------------------------------


def step3_name_forms(
    cur: Any,
    logger: Any,
    all_authorships: Any,
    linked_ids: set,
    name_form_map: dict,
    dry_run: bool,
    *,
    person_repo: PersonRepository,
) -> tuple[int, int, int]:
    """Lookup par author_name_normalized dans person_name_forms."""
    linked = 0
    created = 0
    ambiguous = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        ln, fn = a["last_norm"], a["first_norm"]
        if not ln:
            continue

        person_ids = None
        forms_to_try = [f for f in [f"{fn} {ln}".strip(), f"{ln} {fn}".strip(), ln] if f]
        for form in forms_to_try:
            if form in name_form_map:
                person_ids = name_form_map[form]
                break

        if person_ids is not None:
            if len(person_ids) == 1:
                pid = person_ids[0]
                if not dry_run:
                    link_to_person(cur, pid, [a], repo=person_repo)
                    add_name_form(cur, pid, a["full_name"], repo=person_repo)
                linked_ids.add((a["source"], a["authorship_id"]))
                linked += 1
            else:
                ambiguous += 1
        else:
            if not a.get("allow_create", True):
                ambiguous += 1
                continue
            last = a["last_name"] or a["full_name"] or "?"
            first = a["first_name"] or ""
            if not dry_run:
                pid = create_person(cur, last, first, repo=person_repo)
                link_to_person(cur, pid, [a], repo=person_repo)
                add_identifiers(cur, pid, [a], repo=person_repo)
                add_name_form(cur, pid, a["full_name"], repo=person_repo)
                for form in [f"{fn} {ln}".strip(), f"{ln} {fn}".strip()]:
                    if form:
                        name_form_map[form] = [pid]
            else:
                for form in [f"{fn} {ln}".strip(), f"{ln} {fn}".strip()]:
                    if form:
                        name_form_map[form] = [-1]

            linked_ids.add((a["source"], a["authorship_id"]))
            created += 1

    logger.info(
        f"  {created} personnes créées, {linked} rattachées, {ambiguous} ambiguës (orphelines)"
    )
    return created, linked, ambiguous


# ---------------------------------------------------------------------------
# Orchestrateur
# ---------------------------------------------------------------------------


def run(
    cur: Any,
    conn: Any,
    queries: PersonsCreateQueries,
    logger: Any,
    *,
    person_repo: PersonRepository,
    dry_run: bool = False,
) -> None:
    all_authorships = get_all_unlinked_authorships(cur, queries)
    logger.info(f"{len(all_authorships)} authorships UCA non rattachées (toutes sources)")

    if not all_authorships:
        logger.info("Rien à faire.")
        return

    linked_ids: set[tuple[str, int]] = set()

    logger.info("\n--- Étape 0 : comptes HAL ---")
    s0 = step0_hal_accounts(
        cur, queries, logger, all_authorships, linked_ids, dry_run, person_repo=person_repo
    )

    logger.info("\n--- Étape 1 : cross-source (même publi + position) ---")
    linked_index = load_linked_authorships_by_pub(cur, queries)
    s1 = step1_cross_source(
        cur, logger, all_authorships, linked_ids, linked_index, dry_run, person_repo=person_repo
    )

    logger.info("\n--- Étape 1b : IdRef connu ---")
    s1b = step1b_idref(
        cur, queries, logger, all_authorships, linked_ids, dry_run, person_repo=person_repo
    )

    logger.info("\n--- Étape 2 : ORCID connu ---")
    s2 = step2_orcid(
        cur, queries, logger, all_authorships, linked_ids, dry_run, person_repo=person_repo
    )

    logger.info("\n--- Étape 3 : person_name_forms ---")
    name_form_map = queries.fetch_name_form_map(cur)
    s3_created, s3_linked, s3_ambiguous = step3_name_forms(
        cur,
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
    logger.info(f"  Étape 0 (comptes HAL)    : {s0} rattachées")
    logger.info(f"  Étape 1 (cross-source)   : {s1} rattachées")
    logger.info(f"  Étape 1b (IdRef connu)   : {s1b} rattachées")
    logger.info(f"  Étape 2 (ORCID connu)    : {s2} rattachées")
    logger.info(
        f"  Étape 3 (name_forms)     : {s3_created} créées, {s3_linked} rattachées, "
        f"{s3_ambiguous} ambiguës"
    )
    logger.info(f"  Non résolues             : {unlinked}")

    if dry_run:
        conn.rollback()
        logger.info("\n  (dry-run — rien n'a été modifié)")
    else:
        conn.commit()
        logger.info("\n  ✓ Appliqué.")
        logger.info("  → Lancer build_authorships.py pour propager in_perimeter/structure_ids")
