"""
Peuple la table hal_structures depuis les données de staging HAL,
puis propose des correspondances avec la table structures locale.

Étape 1 : extract  — extrait les structures HAL depuis staging_hal.raw_data
Étape 2 : match    — propose des correspondances hal_structures → structures
Étape 3 : apply    — applique les correspondances validées

Usage:
    python populate_hal_struct_ids.py extract         # peupler hal_structures
    python populate_hal_struct_ids.py match           # proposer les correspondances
    python populate_hal_struct_ids.py apply           # appliquer + copier hal_struct_id vers structures
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from utils.normalize import normalize_text as normalize

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)



# =================================================================
# EXTRACT : staging_hal → hal_structures
# =================================================================

def do_extract(conn):
    """Extrait les structures HAL depuis staging_hal vers hal_structures.

    Utilise structIdName_fs (champ composé "id_FacetSep_nom") qui est
    auto-documenté et fiable. Les champs parallèles (structId_i, structName_s,
    structAcronym_s, structType_s) sont SPARSE et non alignés — on ne les
    utilise PAS.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT raw_data->'structIdName_fs' AS entries
        FROM staging_hal
        WHERE raw_data ? 'structIdName_fs'
    """)

    structs = {}  # hal_struct_id → {name, count}

    for row in cur.fetchall():
        entries = row["entries"] or []
        for entry in entries:
            parts = entry.split("_FacetSep_")
            if len(parts) != 2:
                continue
            try:
                sid = int(parts[0])
            except ValueError:
                continue
            name = parts[1].strip()
            if not name:
                continue

            if sid not in structs:
                structs[sid] = {"name": name, "count": 0}
            structs[sid]["count"] += 1

    logger.info(f"  {len(structs)} structures HAL distinctes extraites")

    inserted = 0
    for hal_id, info in structs.items():
        cur.execute("""
            INSERT INTO hal_structures (hal_struct_id, name, doc_count)
            VALUES (%s, %s, %s)
            ON CONFLICT (hal_struct_id) DO UPDATE SET
                name = EXCLUDED.name,
                doc_count = EXCLUDED.doc_count
        """, (hal_id, info["name"], info["count"]))
        inserted += 1

    conn.commit()
    logger.info(f"  {inserted} hal_structures insérées/mises à jour")

    cur.close()


# =================================================================
# MATCH : hal_structures ↔ structures
# =================================================================

def do_match(conn):
    """Propose des correspondances entre hal_structures et structures.

    Matching par nom normalisé uniquement. On compare :
    - notre nom normalisé ↔ nom HAL normalisé
    - notre acronyme ↔ nom HAL normalisé (certaines structures HAL portent l'acronyme comme nom)
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Nos structures
    cur.execute("""
        SELECT s.id, s.code, s.name, s.acronym, s.type::text,
               s.hal_collection,
               EXISTS (SELECT 1 FROM hal_structures hs WHERE hs.structure_id = s.id) AS has_hal_link
        FROM structures s
        ORDER BY s.type, s.name
    """)
    our_structs = cur.fetchall()

    # Toutes les structures HAL
    cur.execute("""
        SELECT hal_struct_id, name, doc_count, structure_id
        FROM hal_structures
        ORDER BY doc_count DESC
    """)
    hal_structs = cur.fetchall()

    # Index par nom normalisé
    hal_by_name = {}
    for h in hal_structs:
        norm = normalize(h["name"])
        if norm:
            hal_by_name.setdefault(norm, []).append(h)

    logger.info(f"Nos structures : {len(our_structs)}")
    logger.info(f"Structures HAL : {len(hal_structs)}")
    logger.info(f"")

    matches = []
    ambiguous = []

    for s in our_structs:
        already = s["has_hal_link"]
        if already:
            logger.info(f"  ✓ [{s['type']}] {s['name']} ({s['acronym']}) → déjà lié")
            continue

        candidates = set()
        our_norm = normalize(s["name"])
        our_acro = normalize(s["acronym"])

        # Match exact par nom normalisé
        for h in hal_by_name.get(our_norm, []):
            candidates.add(h["hal_struct_id"])

        # Match notre acronyme ↔ nom HAL (ex: "IP" dans structures ↔ "IP" comme nom HAL)
        if our_acro and len(our_acro) >= 3:
            for h in hal_by_name.get(our_acro, []):
                candidates.add(h["hal_struct_id"])

        if not candidates:
            logger.info(f"  ✗ [{s['type']}] {s['name']} ({s['acronym']}) → aucun candidat")
            continue

        cands = [h for h in hal_structs if h["hal_struct_id"] in candidates]
        cands.sort(key=lambda h: h["doc_count"], reverse=True)

        if len(cands) == 1:
            c = cands[0]
            logger.info(f"  → [{s['type']}] {s['name']} ({s['acronym']})"
                        f" → HAL#{c['hal_struct_id']} {c['name']}"
                        f" ({c['doc_count']} docs)")
            matches.append((s["id"], c["hal_struct_id"]))
        else:
            logger.info(f"  ? [{s['type']}] {s['name']} ({s['acronym']}) → {len(cands)} candidats :")
            for c in cands[:5]:
                logger.info(f"      HAL#{c['hal_struct_id']} {c['name']}"
                            f" ({c['doc_count']} docs)"
                            f" {'★ déjà lié' if c['structure_id'] else ''}")
            ambiguous.append((s, cands))

    logger.info(f"\n=== Résumé ===")
    logger.info(f"  Matchs uniques  : {len(matches)}")
    logger.info(f"  Ambigus         : {len(ambiguous)}")
    logger.info(f"  → Lancer 'apply' pour appliquer les matchs uniques")

    cur.close()
    return matches


# =================================================================
# APPLY : écrire les correspondances
# =================================================================

def do_apply(conn):
    """Applique les matchs et copie hal_struct_id vers structures."""
    matches = do_match(conn)

    if not matches:
        logger.info("Rien à appliquer.")
        return

    cur = conn.cursor(cursor_factory=RealDictCursor)

    for struct_id, hal_struct_id in matches:
        # Lier hal_structures → structures
        cur.execute("""
            UPDATE hal_structures SET structure_id = %s
            WHERE hal_struct_id = %s
        """, (struct_id, hal_struct_id))

    conn.commit()
    logger.info(f"\n  {len(matches)} correspondances appliquées.")
    cur.close()


# =================================================================

def main():
    parser = argparse.ArgumentParser(description="Structures HAL → structures locales")
    parser.add_argument("action", choices=["extract", "match", "apply"],
                        help="extract: peupler hal_structures ; match: proposer ; apply: appliquer")
    args = parser.parse_args()

    conn = get_connection()

    if args.action == "extract":
        do_extract(conn)
    elif args.action == "match":
        do_match(conn)
    elif args.action == "apply":
        do_apply(conn)

    conn.close()


if __name__ == "__main__":
    main()
