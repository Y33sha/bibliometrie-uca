"""
Corrige le doc_type des publications OpenAlex dont la source est "theses.fr (ABES)"
mais qui sont typées article, preprint, dataset, etc. au lieu de thesis.

Usage:
    python scripts/fix_openalex_theses_doc_types.py              # dry-run
    python scripts/fix_openalex_theses_doc_types.py --apply       # appliquer
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from utils.log import setup_logger

logger = setup_logger("fix_oa_theses_types", os.path.join(os.path.dirname(__file__), "../processing/logs"))


def find_mistyped(cur):
    """Trouve les pubs OA avec source theses.fr mais doc_type != thesis."""
    cur.execute("""
        SELECT DISTINCT p.id, p.doc_type::text, p.title
        FROM source_documents sd
        JOIN staging st ON st.id = sd.staging_id
        JOIN publications p ON p.id = sd.publication_id
        WHERE sd.source = 'openalex'
          AND st.raw_data->'primary_location'->'source'->>'display_name' LIKE '%%theses.fr%%'
          AND p.doc_type NOT IN ('thesis', 'ongoing_thesis')
        ORDER BY p.id
    """)
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description="Corrige les doc_types OA theses.fr")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        rows = find_mistyped(cur)
        logger.info(f"Publications OA theses.fr à corriger : {len(rows)}")

        for row in rows:
            label = f"pub {row['id']} ({row['doc_type']} → thesis)"
            if args.apply:
                cur.execute(
                    "UPDATE publications SET doc_type = 'thesis', updated_at = now() WHERE id = %s",
                    (row["id"],))
                logger.info(f"  FIX  {label}")
            else:
                logger.info(f"  DRY  {label}")

        if args.apply:
            conn.commit()

        logger.info(f"\n{'Appliqué' if args.apply else 'Dry-run'} : {len(rows)} publications")
        if not args.apply and rows:
            logger.info("Ajouter --apply pour appliquer.")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
