"""
Peuple la table source_structures (source='hal') depuis les données de staging HAL,
puis propose des correspondances avec la table structures locale.

Étape 1 : extract  — extrait les structures HAL depuis staging.raw_data
Étape 2 : match    — propose des correspondances source_structures → structures
Étape 3 : apply    — applique les correspondances validées

Usage:
    python map_hal_structures.py extract         # peupler source_structures (hal)
    python map_hal_structures.py match           # proposer les correspondances
    python map_hal_structures.py apply           # appliquer
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
# EXTRACT : staging → source_structures (hal)
# =================================================================

def do_extract(conn):
    """Extrait les structures HAL depuis staging vers source_structures (source='hal').

    Utilise structIdName_fs (champ composé "id_FacetSep_nom") qui est
    auto-documenté et fiable. Les champs parallèles (structId_i, structName_s,
    structAcronym_s, structType_s) sont SPARSE et non alignés — on ne les
    utilise PAS.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT raw_data->'structIdName_fs' AS entries
        FROM staging
        WHERE source = 'hal' AND raw_data ? 'structIdName_fs'
    """)

    structs = {}  # hal_struct_id (str) → {name, count}

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

            sid_str = str(sid)
            if sid_str not in structs:
                structs[sid_str] = {"name": name, "count": 0}
            structs[sid_str]["count"] += 1

    logger.info(f"  {len(structs)} structures HAL distinctes extraites")

    inserted = 0
    for source_id, info in structs.items():
        from psycopg2.extras import Json
        source_data = Json({"doc_count": info["count"]})
        cur.execute("""
            INSERT INTO source_structures (source, source_id, name, source_data)
            VALUES ('hal', %s, %s, %s)
            ON CONFLICT (source, source_id) DO UPDATE SET
                name = EXCLUDED.name,
                source_data = COALESCE(source_structures.source_data, '{}') ||
                              EXCLUDED.source_data
        """, (source_id, info["name"], source_data))
        inserted += 1

    conn.commit()
    logger.info(f"  {inserted} source_structures (hal) insérées/mises à jour")

    cur.close()


# =================================================================
# MATCH : source_structures (hal) ↔ structures
# =================================================================

def do_match(conn):
    """Propose des correspondances entre source_structures (hal) et structures.

    Matching par nom normalisé uniquement. On compare :
    - notre nom normalisé ↔ nom HAL normalisé
    - notre acronyme ↔ nom HAL normalisé (certaines structures HAL portent l'acronyme comme nom)
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Nos structures
    cur.execute("""
        SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text,
               s.hal_collection,
               EXISTS (
                   SELECT 1 FROM source_structures ss
                   WHERE ss.source = 'hal' AND ss.structure_id = s.id
               ) AS has_hal_link
        FROM structures s
        ORDER BY s.structure_type, s.name
    """)
    our_structs = cur.fetchall()

    # Toutes les structures HAL
    cur.execute("""
        SELECT source_id AS hal_struct_id, name,
               (source_data->>'doc_count')::int AS doc_count,
               structure_id
        FROM source_structures
        WHERE source = 'hal'
        ORDER BY (source_data->>'doc_count')::int DESC NULLS LAST
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
    """Applique les matchs : lie source_structures (hal) → structures."""
    matches = do_match(conn)

    if not matches:
        logger.info("Rien à appliquer.")
        return

    cur = conn.cursor(cursor_factory=RealDictCursor)

    for struct_id, hal_struct_id in matches:
        # Lier source_structures → structures
        cur.execute("""
            UPDATE source_structures SET structure_id = %s
            WHERE source = 'hal' AND source_id = %s
        """, (struct_id, str(hal_struct_id)))

    conn.commit()
    logger.info(f"\n  {len(matches)} correspondances appliquées.")
    cur.close()


# =================================================================

def main():
    parser = argparse.ArgumentParser(description="Structures HAL → structures locales")
    parser.add_argument("action", choices=["extract", "match", "apply"],
                        help="extract: peupler source_structures (hal) ; match: proposer ; apply: appliquer")
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
