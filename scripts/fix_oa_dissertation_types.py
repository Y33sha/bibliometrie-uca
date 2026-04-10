"""
Corrige le doc_type des publications OpenAlex de type "dissertation" qui
pointent vers DUMAS (mémoires de master, pas des thèses).

Règle : si primary_location URL contient "dumas." → doc_type = memoir.

Usage:
    python scripts/fix_oa_dissertation_types.py              # dry-run
    python scripts/fix_oa_dissertation_types.py --apply       # appliquer
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from utils.log import setup_logger

logger = setup_logger("fix_oa_diss", os.path.join(os.path.dirname(__file__), "../processing/logs"))


def find_dumas_dissertations(cur):
    """Trouve les publications OA dissertation pointant vers DUMAS, typées thesis."""
    cur.execute("""
        SELECT p.id, p.doc_type::text, p.title,
               st.raw_data->'primary_location'->>'landing_page_url' AS url
        FROM source_documents sd
        JOIN staging st ON st.id = sd.staging_id
        JOIN publications p ON p.id = sd.publication_id
        WHERE sd.source = 'openalex'
          AND st.raw_data->>'type' = 'dissertation'
          AND st.raw_data->'primary_location'->>'landing_page_url' LIKE '%%dumas.%%'
          AND p.doc_type != 'memoir'
        ORDER BY p.pub_year DESC, p.id
    """)
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description="Corrige les dissertations DUMAS en mémoires")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        rows = find_dumas_dissertations(cur)
        logger.info(f"Publications DUMAS à corriger : {len(rows)}")

        for row in rows:
            label = f"pub {row['id']} ({row['doc_type']} → memoir) {row['url']}"
            if args.apply:
                cur.execute(
                    "UPDATE publications SET doc_type = 'memoir', updated_at = now() WHERE id = %s",
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
