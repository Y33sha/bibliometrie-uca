"""
Crée des entités Personnes à partir des authorships sources UCA non rattachées.

Algorithme en 4 étapes :

  Étape 0 : Comptes HAL
    hal_authors avec hal_person_id → création/mapping personne, propagation
    aux authorships liées. Récupération ORCID, idHAL.

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

Usage:
    python create_persons_from_source_authorships.py              # exécuter
    python create_persons_from_source_authorships.py --dry-run    # dry-run
"""

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from utils.normalize import normalize_name
from utils.names import parse_raw_author_name, names_compatible
from services.persons import (
    create_person, link_authorships as link_to_person,
    add_identifiers_from_authorships as add_identifiers,
    add_name_form,
)

from utils.log import setup_logger

logger = setup_logger("create_persons", os.path.join(os.path.dirname(__file__), "logs"))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def get_all_unlinked_authorships(cur):
    """Récupère toutes les authorships UCA sans person_id, toutes sources."""
    # HAL
    cur.execute("""
        SELECT has.id AS authorship_id, 'hal' AS source,
               ha.full_name, ha.last_name, ha.first_name,
               ha.orcid, ha.idhal,
               ha.id AS hal_author_id,
               (ha.hal_person_id IS NOT NULL) AS has_hal_person_id,
               ha.hal_person_id,
               hd.publication_id,
               has.author_position
        FROM hal_authorships has
        JOIN hal_authors ha ON ha.id = has.hal_author_id
        JOIN hal_documents hd ON hd.id = has.hal_document_id
        WHERE has.person_id IS NULL
          AND has.is_uca = TRUE
          AND hd.publication_id IS NOT NULL
    """)
    hal_rows = cur.fetchall()

    # OpenAlex
    cur.execute("""
        SELECT oas.id AS authorship_id, 'openalex' AS source,
               oas.raw_author_name AS full_name,
               NULL::text AS last_name, NULL::text AS first_name,
               oa.orcid, NULL::text AS idhal,
               NULL::int AS hal_author_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               od.publication_id,
               oas.author_position
        FROM openalex_authorships oas
        JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
        JOIN openalex_documents od ON od.id = oas.openalex_document_id
        WHERE oas.person_id IS NULL
          AND oas.is_uca = TRUE
          AND oas.raw_author_name IS NOT NULL
          AND od.publication_id IS NOT NULL
    """)
    oa_rows = cur.fetchall()

    # WoS
    cur.execute("""
        SELECT was.id AS authorship_id, 'wos' AS source,
               wa.full_name, wa.last_name, wa.first_name,
               wa.orcid, NULL::text AS idhal,
               NULL::int AS hal_author_id,
               FALSE AS has_hal_person_id,
               NULL::int AS hal_person_id,
               wd.publication_id,
               was.author_position
        FROM wos_authorships was
        JOIN wos_authors wa ON wa.id = was.wos_author_id
        JOIN wos_documents wd ON wd.id = was.wos_document_id
        WHERE was.person_id IS NULL
          AND was.is_uca = TRUE
          AND wd.publication_id IS NOT NULL
    """)
    wos_rows = cur.fetchall()

    # Enrichir avec last_name/first_name parsés pour OA
    all_rows = []
    for r in hal_rows + oa_rows + wos_rows:
        r = dict(r)
        if not r.get("last_name"):
            r["last_name"], r["first_name"] = parse_raw_author_name(r["full_name"])
        r["last_norm"] = normalize_name(r["last_name"])
        r["first_norm"] = normalize_name(r["first_name"])
        all_rows.append(r)

    return all_rows


def load_linked_authorships_by_pub(cur):
    """Charge les authorships déjà rattachées à une personne, indexées par
    (publication_id, author_position) pour le cross-source matching.

    Retourne : {(pub_id, position): [(person_id, last_norm, first_norm, source), ...]}
    """
    index = defaultdict(list)

    cur.execute("""
        SELECT has.person_id, has.author_position,
               hd.publication_id,
               ha.last_name, ha.first_name, ha.full_name,
               'hal' AS source
        FROM hal_authorships has
        JOIN hal_authors ha ON ha.id = has.hal_author_id
        JOIN hal_documents hd ON hd.id = has.hal_document_id
        WHERE has.person_id IS NOT NULL
          AND hd.publication_id IS NOT NULL
    """)
    for r in cur.fetchall():
        ln = normalize_name(r["last_name"] or "")
        fn = normalize_name(r["first_name"] or "")
        if not ln and r["full_name"]:
            last, first = parse_raw_author_name(r["full_name"])
            ln, fn = normalize_name(last), normalize_name(first)
        index[(r["publication_id"], r["author_position"])].append(
            (r["person_id"], ln, fn, r["source"]))

    cur.execute("""
        SELECT oas.person_id, oas.author_position,
               od.publication_id,
               oas.raw_author_name AS full_name,
               'openalex' AS source
        FROM openalex_authorships oas
        JOIN openalex_documents od ON od.id = oas.openalex_document_id
        WHERE oas.person_id IS NOT NULL
          AND od.publication_id IS NOT NULL
    """)
    for r in cur.fetchall():
        last, first = parse_raw_author_name(r["full_name"])
        ln, fn = normalize_name(last), normalize_name(first)
        index[(r["publication_id"], r["author_position"])].append(
            (r["person_id"], ln, fn, r["source"]))

    cur.execute("""
        SELECT was.person_id, was.author_position,
               wd.publication_id,
               wa.last_name, wa.first_name,
               'wos' AS source
        FROM wos_authorships was
        JOIN wos_authors wa ON wa.id = was.wos_author_id
        JOIN wos_documents wd ON wd.id = was.wos_document_id
        WHERE was.person_id IS NOT NULL
          AND wd.publication_id IS NOT NULL
    """)
    for r in cur.fetchall():
        ln = normalize_name(r["last_name"] or "")
        fn = normalize_name(r["first_name"] or "")
        index[(r["publication_id"], r["author_position"])].append(
            (r["person_id"], ln, fn, r["source"]))

    return index


def load_name_form_map(cur):
    """Charge person_name_forms.

    Retourne : {name_form: [person_id, ...]}
    """
    cur.execute("SELECT name_form, person_ids FROM person_name_forms")
    return {r["name_form"]: r["person_ids"] for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Étape 0 : Comptes HAL
# ---------------------------------------------------------------------------

def step0_hal_accounts(cur, all_authorships, linked_ids, dry_run):
    """hal_authors avec hal_person_id → création/mapping personne."""
    by_hal_pid = defaultdict(list)
    for a in all_authorships:
        if a["source"] == "hal" and a["has_hal_person_id"]:
            by_hal_pid[a["hal_person_id"]].append(a)

    # hal_authors déjà liés à une personne
    cur.execute("""
        SELECT ha.hal_person_id, ha.person_id
        FROM hal_authors ha
        WHERE ha.hal_person_id IS NOT NULL AND ha.person_id IS NOT NULL
    """)
    hal_person_map = {r["hal_person_id"]: r["person_id"] for r in cur.fetchall()}

    linked = 0
    created = 0
    for hal_pid, group in by_hal_pid.items():
        existing_pid = hal_person_map.get(hal_pid)
        if existing_pid:
            if not dry_run:
                link_to_person(cur, existing_pid, group)
                add_identifiers(cur, existing_pid, group)
        else:
            best = max(group, key=lambda a: 1)  # pick any
            last = best["last_name"] or ""
            first = best["first_name"] or ""
            if not dry_run:
                pid = create_person(cur, last, first)
                link_to_person(cur, pid, group)
                add_identifiers(cur, pid, group)
            created += 1

        linked += len(group)
        for a in group:
            linked_ids.add((a["source"], a["authorship_id"]))

    logger.info(f"  {created} personnes créées, {linked} authorships rattachées")
    return linked


# ---------------------------------------------------------------------------
# Étape 1 : Cross-source (même publication + même position)
# ---------------------------------------------------------------------------

def step1_cross_source(cur, all_authorships, linked_ids, linked_index, dry_run):
    """Pour chaque authorship sans person_id, chercher sur la même publication
    (même position) une authorship d'une autre source rattachée à une personne.
    """
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

        # Chercher un candidat d'une autre source avec nom compatible
        matched_pid = None
        for pid, ln, fn, src in candidates:
            if src == a["source"]:
                continue  # même source, pas utile
            if names_compatible(a["last_norm"], a["first_norm"], ln, fn):
                if matched_pid is not None and matched_pid != pid:
                    matched_pid = None  # ambiguïté
                    break
                matched_pid = pid

        if matched_pid:
            if not dry_run:
                link_to_person(cur, matched_pid, [a])
                add_name_form(cur, matched_pid, a["full_name"])
            linked_ids.add((a["source"], a["authorship_id"]))
            # Mettre à jour l'index pour les passes suivantes
            ln, fn = a["last_norm"], a["first_norm"]
            linked_index[(pub_id, position)].append(
                (matched_pid, ln, fn, a["source"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par cross-source")
    return linked


# ---------------------------------------------------------------------------
# Étape 2 : ORCID connu
# ---------------------------------------------------------------------------

def load_orcid_person_map(cur):
    """Charge les ORCID déjà mappés à une personne (status != rejected).

    Retourne : {orcid: person_id}
    """
    cur.execute("""
        SELECT id_value, person_id
        FROM person_identifiers
        WHERE id_type = 'orcid'
          AND status != 'rejected'
    """)
    return {r["id_value"]: r["person_id"] for r in cur.fetchall()}


def step2_orcid(cur, all_authorships, linked_ids, dry_run):
    """Si l'authorship a un ORCID déjà connu en base (non rejeté),
    rattacher à la personne correspondante.
    """
    orcid_map = load_orcid_person_map(cur)
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
                link_to_person(cur, pid, [a])
                add_name_form(cur, pid, a["full_name"])
            linked_ids.add((a["source"], a["authorship_id"]))
            linked += 1

    logger.info(f"  {linked} authorships rattachées par ORCID connu")
    return linked


# ---------------------------------------------------------------------------
# Étape 3 : Lookup person_name_forms
# ---------------------------------------------------------------------------

def step3_name_forms(cur, all_authorships, linked_ids, name_form_map, dry_run):
    """Lookup par author_name_normalized dans person_name_forms.

    - Mappé à 1 personne → rattacher
    - Mappé à >1 personnes → orphelin (traitement manuel)
    - Forme inconnue → créer nouvelle personne
    """
    linked = 0
    created = 0
    ambiguous = 0

    for a in all_authorships:
        if (a["source"], a["authorship_id"]) in linked_ids:
            continue

        ln, fn = a["last_norm"], a["first_norm"]
        if not ln:
            continue

        # Chercher dans les name_forms (essayer les deux ordres)
        person_ids = None
        for form in [f"{fn} {ln}", f"{ln} {fn}", ln]:
            if form and form in name_form_map:
                person_ids = name_form_map[form]
                break

        if person_ids is not None:
            if len(person_ids) == 1:
                # Unique → rattacher
                pid = person_ids[0]
                if not dry_run:
                    link_to_person(cur, pid, [a])
                    add_name_form(cur, pid, a["full_name"])
                linked_ids.add((a["source"], a["authorship_id"]))
                linked += 1
            else:
                # Ambigu → orphelin
                ambiguous += 1
        else:
            # Forme inconnue → créer personne
            last = a["last_name"] or a["full_name"] or "?"
            first = a["first_name"] or ""
            if not dry_run:
                pid = create_person(cur, last, first)
                link_to_person(cur, pid, [a])
                add_identifiers(cur, pid, [a])
                add_name_form(cur, pid, a["full_name"])
                # Enregistrer la nouvelle forme pour les authorships suivantes
                for form in [f"{fn} {ln}", f"{ln} {fn}"]:
                    if form.strip():
                        name_form_map[form] = [pid]
            else:
                for form in [f"{fn} {ln}", f"{ln} {fn}"]:
                    if form.strip():
                        name_form_map[form] = [-1]  # placeholder dry-run

            linked_ids.add((a["source"], a["authorship_id"]))
            created += 1

    logger.info(f"  {created} personnes créées, {linked} rattachées, {ambiguous} ambiguës (orphelines)")
    return created, linked, ambiguous


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run=False):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    all_authorships = get_all_unlinked_authorships(cur)
    logger.info(f"{len(all_authorships)} authorships UCA non rattachées (toutes sources)")

    if not all_authorships:
        logger.info("Rien à faire.")
        conn.close()
        return

    linked_ids = set()  # (source, authorship_id)

    # ── Étape 0 : Comptes HAL ──
    logger.info("\n--- Étape 0 : comptes HAL ---")
    s0 = step0_hal_accounts(cur, all_authorships, linked_ids, dry_run)

    # ── Étape 1 : Cross-source ──
    logger.info("\n--- Étape 1 : cross-source (même publi + position) ---")
    linked_index = load_linked_authorships_by_pub(cur)
    s1 = step1_cross_source(cur, all_authorships, linked_ids, linked_index, dry_run)

    # ── Étape 2 : ORCID connu ──
    logger.info("\n--- Étape 2 : ORCID connu ---")
    s2 = step2_orcid(cur, all_authorships, linked_ids, dry_run)

    # ── Étape 3 : Name forms ──
    logger.info("\n--- Étape 3 : person_name_forms ---")
    name_form_map = load_name_form_map(cur)
    s3_created, s3_linked, s3_ambiguous = step3_name_forms(
        cur, all_authorships, linked_ids, name_form_map, dry_run)

    # ── Résumé ──
    total_linked = len(linked_ids)
    unlinked = len(all_authorships) - total_linked

    logger.info(f"\n=== Résumé ===")
    logger.info(f"  Étape 0 (comptes HAL)    : {s0} rattachées")
    logger.info(f"  Étape 1 (cross-source)   : {s1} rattachées")
    logger.info(f"  Étape 2 (ORCID connu)    : {s2} rattachées")
    logger.info(f"  Étape 3 (name_forms)     : {s3_created} créées, {s3_linked} rattachées, {s3_ambiguous} ambiguës")
    logger.info(f"  Non résolues             : {unlinked}")

    if dry_run:
        conn.rollback()
        logger.info("\n  (dry-run — rien n'a été modifié)")
    else:
        conn.commit()
        logger.info("\n  ✓ Appliqué.")
        logger.info("  → Lancer build_authorships.py pour propager is_uca/structure_ids")

    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Crée des personnes à partir des authorships sources UCA"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Simuler sans modifier la base")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
