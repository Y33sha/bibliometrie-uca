"""
Résolution des adresses : identification UCA + rattachement structures.

Lit les formes de noms depuis la table name_forms,
et enregistre dans address_structures avec matched_form_id pour
la traçabilité (boucle de rétroaction).

Schéma v2 :
  - address_structures (address_id, structure_id, matched_form_id, is_confirmed)
  - matched_form_id IS NOT NULL = détection auto
  - matched_form_id IS NULL + is_confirmed = assignation manuelle

Usage:
    python resolve_addresses.py              # résoudre les adresses non traitées
    python resolve_addresses.py --reset      # remettre à zéro (auto uniquement)
    python resolve_addresses.py --rerun      # reset auto + relancer tout
    python resolve_addresses.py --stats      # stats
"""

import argparse
import logging
import os
import re
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "resolve_addresses.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


# ─── Normalisation ───────────────────────────────────────────────

def normalize(text):
    """Normalise pour le matching : minuscules, sans accents, sans ponctuation.

    DOIT être identique à la normalisation utilisée dans seed_structures.py
    pour form_normalized."""
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ─── Chargement des données ──────────────────────────────────────

def load_forms(cur):
    """Charge toutes les formes actives depuis name_forms."""
    cur.execute("""
        SELECT nf.id, nf.structure_id, nf.form_text, nf.form_normalized,
               nf.is_regex, nf.requires_context_of,
               s.code AS struct_code, s.type::text AS struct_type
        FROM name_forms nf
        JOIN structures s ON s.id = nf.structure_id
        WHERE nf.is_active = TRUE
        ORDER BY nf.id
    """)
    columns = [desc[0] for desc in cur.description]
    forms = [dict(zip(columns, row)) for row in cur.fetchall()]
    logger.info(f"  {len(forms)} formes actives chargées")
    return forms


def load_tutelles(cur):
    """Charge le mapping structure_id → set(tutelle_ids)."""
    cur.execute("""
        SELECT child_id, parent_id
        FROM structure_relations
        WHERE relation_type = 'est_tutelle_de'
    """)
    tutelles = {}
    for child_id, parent_id in cur.fetchall():
        tutelles.setdefault(child_id, set()).add(parent_id)
    return tutelles


def load_uca_perimeter(cur):
    """Construit l'ensemble des structure_ids dans le périmètre UCA.

    Inclut :
    - UCA elle-même
    - Les structures dont UCA est tutelle (labos UCA)

    N'inclut PAS les partenaires (CHU, INP…) ni les tutelles nationales
    (CNRS, Inserm…) car leurs publications ne sont pas forcément UCA.
    """
    cur.execute("SELECT id FROM structures WHERE code = 'uca'")
    row = cur.fetchone()
    if not row:
        logger.warning("Structure UCA introuvable ! Le flag is_uca sera toujours FALSE.")
        return set()

    uca_id = row[0]
    perimeter = {uca_id}

    # Structures dont UCA est tutelle (parent=UCA → child=labo)
    cur.execute("""
        SELECT child_id FROM structure_relations
        WHERE parent_id = %s AND relation_type = 'est_tutelle_de'
    """, (uca_id,))
    for r in cur.fetchall():
        perimeter.add(r[0])

    return perimeter


# ─── Matching ────────────────────────────────────────────────────

def match_form_in_text(form, text_normalized):
    """Vérifie si une forme matche dans le texte normalisé."""
    if form["is_regex"]:
        try:
            return bool(re.search(form["form_text"], text_normalized, re.IGNORECASE))
        except re.error:
            return False

    form_norm = form["form_normalized"]
    if not form_norm:
        return False

    if len(form_norm) <= 6:
        pattern = r"(?<![a-z0-9])" + re.escape(form_norm) + r"(?![a-z0-9])"
        return bool(re.search(pattern, text_normalized))
    else:
        return form_norm in text_normalized


def build_forms_by_structure(forms):
    """Index : structure_id → [forms]."""
    idx = {}
    for f in forms:
        idx.setdefault(f["structure_id"], []).append(f)
    return idx


def has_form_match_for_structure(struct_id, text_normalized, forms_by_structure):
    """Vérifie si au moins une forme de la structure donnée matche."""
    for f in forms_by_structure.get(struct_id, []):
        if match_form_in_text(f, text_normalized):
            return True
    return False


def resolve_context(requires_context_of, structure_id, tutelles_map):
    """Résout requires_context_of en un set d'IDs de structures.

    - Entiers → IDs directs
    - "tutelles" → tutelles de la structure via structure_relations
    """
    if not requires_context_of:
        return set()

    result = set()
    for item in requires_context_of:
        if item == "tutelles":
            result.update(tutelles_map.get(structure_id, set()))
        elif isinstance(item, int):
            result.add(item)
    return result


def resolve_address(text_normalized, forms, forms_by_structure, tutelles_map):
    """Résout une adresse : trouve toutes les structures identifiées.

    Retourne une liste de (structure_id, form_id).
    """
    matches = []
    seen_structures = set()

    for f in forms:
        sid = f["structure_id"]
        if sid in seen_structures:
            continue

        if not match_form_in_text(f, text_normalized):
            continue

        # Vérifier le contexte
        ctx = f["requires_context_of"]
        if ctx:
            context_ids = resolve_context(ctx, sid, tutelles_map)
            if not context_ids:
                continue

            context_satisfied = any(
                has_form_match_for_structure(cid, text_normalized, forms_by_structure)
                for cid in context_ids
            )
            if not context_satisfied:
                continue

        matches.append((sid, f["id"]))
        seen_structures.add(sid)

    return matches


# ─── Statistiques ────────────────────────────────────────────────

def show_stats(cur):
    cur.execute("SELECT COUNT(*) FROM addresses")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT a.id)
        FROM addresses a
        JOIN address_structures ast ON ast.address_id = a.id
    """)
    with_struct = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT a.id)
        FROM addresses a
        JOIN address_structures ast ON ast.address_id = a.id
        WHERE ast.matched_form_id IS NOT NULL
    """)
    auto_detected = cur.fetchone()[0]

    logger.info(f"\n--- Statistiques adresses ---")
    logger.info(f"  Total             : {total}")
    logger.info(f"  Avec structure(s) : {with_struct}")
    logger.info(f"  Auto-détectées    : {auto_detected}")
    logger.info(f"  Sans structure    : {total - with_struct}")

    cur.execute("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE matched_form_id IS NOT NULL) AS auto,
            COUNT(*) FILTER (WHERE matched_form_id IS NULL AND is_confirmed = TRUE) AS manual
        FROM address_structures
    """)
    row = cur.fetchone()
    logger.info(f"\n--- Affiliations (address_structures) ---")
    logger.info(f"  Total         : {row[0]}")
    logger.info(f"  Auto          : {row[1]}")
    logger.info(f"  Manuelles     : {row[2]}")

    cur.execute("""
        SELECT COALESCE(s.acronym, s.name, '?') AS label,
               s.type::text AS stype,
               COUNT(*) AS nb
        FROM address_structures ast
        JOIN structures s ON s.id = ast.structure_id
        WHERE ast.matched_form_id IS NOT NULL
        GROUP BY 1, 2
        ORDER BY nb DESC
        LIMIT 20
    """)
    rows = cur.fetchall()
    if rows:
        logger.info(f"\n  Top structures (auto) :")
        for row in rows:
            logger.info(f"    {row[0]:<30s} [{row[1]}]  {row[2]}")


# ─── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true",
                        help="Supprime les affiliations auto")
    parser.add_argument("--rerun", action="store_true",
                        help="Reset auto puis relance la résolution complète")
    parser.add_argument("--stats", action="store_true",
                        help="Affiche les statistiques")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.stats:
        show_stats(cur)
        conn.close()
        return

    if args.reset or args.rerun:
        # Supprimer les affiliations auto-détectées (matched_form_id IS NOT NULL)
        cur.execute("DELETE FROM address_structures WHERE matched_form_id IS NOT NULL")
        affils = cur.rowcount
        conn.commit()
        logger.info(f"Reset : {affils} affiliations auto supprimées")
        if args.reset and not args.rerun:
            conn.close()
            return

    # Charger les données
    logger.info("Chargement des structures et formes...")
    forms = load_forms(cur)
    forms_by_structure = build_forms_by_structure(forms)
    tutelles_map = load_tutelles(cur)
    uca_perimeter = load_uca_perimeter(cur)
    logger.info(f"  {len(tutelles_map)} structures avec tutelles")
    logger.info(f"  {len(uca_perimeter)} structures dans le périmètre UCA")

    # Adresses sans détection auto
    cur.execute("""
        SELECT a.id, a.raw_text FROM addresses a
        WHERE NOT EXISTS (
            SELECT 1 FROM address_structures ast
            WHERE ast.address_id = a.id AND ast.matched_form_id IS NOT NULL
        )
        ORDER BY a.id
    """)
    rows = cur.fetchall()
    total = len(rows)
    logger.info(f"  {total} adresses à résoudre")

    if total > 0:
        process_addresses(
            cur, conn, rows, forms, forms_by_structure, tutelles_map,
            uca_perimeter
        )

    show_stats(cur)
    conn.close()


def process_addresses(cur, conn, rows, forms, forms_by_structure, tutelles_map,
                      uca_perimeter):
    """Traite une liste d'adresses : détection + affiliations."""
    t_start = time.perf_counter()
    total = len(rows)
    processed = 0
    uca_count = 0
    affil_count = 0

    for addr_id, raw_text in rows:
        text_norm = normalize(raw_text)
        matches = resolve_address(text_norm, forms, forms_by_structure, tutelles_map)

        is_uca = any(sid in uca_perimeter for sid, _ in matches)
        if is_uca:
            uca_count += 1

        # Insérer les structures détectées
        for structure_id, form_id in matches:
            affil_count += 1
            cur.execute("""
                INSERT INTO address_structures
                    (address_id, structure_id, matched_form_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (address_id, structure_id)
                    DO UPDATE SET matched_form_id = EXCLUDED.matched_form_id
                    WHERE address_structures.matched_form_id IS NULL
                      AND address_structures.is_confirmed IS NULL
            """, (addr_id, structure_id, form_id))

        processed += 1
        if processed % BATCH_SIZE == 0:
            conn.commit()
            elapsed = time.perf_counter() - t_start
            rate = processed / elapsed
            logger.info(
                f"  {processed}/{total} "
                f"({uca_count} UCA, {affil_count} affiliations) "
                f"— {rate:.0f} addr/s"
            )

    conn.commit()

    elapsed = time.perf_counter() - t_start
    if total > 0:
        logger.info(f"\n=== Terminé en {elapsed:.1f}s ===")
        logger.info(f"  Adresses traitées : {processed}")
        logger.info(f"  UCA               : {uca_count} ({100*uca_count/processed:.1f}%)")
        logger.info(f"  Affiliations      : {affil_count}")

    return uca_count, affil_count


if __name__ == "__main__":
    main()
