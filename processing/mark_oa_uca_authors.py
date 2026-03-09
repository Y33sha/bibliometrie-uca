"""
Marque les publication_authors qu'OpenAlex identifie comme UCA via le lineage.

Parcourt le raw_json des publication_sources OpenAlex, vérifie pour chaque
authorship si une de ses institutions a UCA dans son lineage.

Usage:
    python mark_oa_uca_authors.py
"""

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# OpenAlex ID de l'UCA
UCA_OA_ID = "https://openalex.org/I198244214"

BATCH_SIZE = 500


def main():
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # Reset
    cur.execute("""
        UPDATE publication_authors SET is_uca_openalex = FALSE
        WHERE source = 'openalex' AND is_uca_openalex = TRUE
    """)
    logger.info(f"Reset : {cur.rowcount} lignes")
    conn.commit()

    # Récupérer toutes les publication_sources OpenAlex avec leur raw_json
    logger.info("Extraction des authorships depuis les raw_json OpenAlex...")

    cur.execute("""
        SELECT ps.publication_id, ps.raw_json->'authorships' AS authorships
        FROM publication_sources ps
        WHERE ps.source = 'openalex'
          AND ps.raw_json->'authorships' IS NOT NULL
    """)
    rows = cur.fetchall()
    logger.info(f"  {len(rows)} publications à traiter")

    t_start = time.perf_counter()
    processed = 0
    marked = 0

    for pub_id, authorships in rows:
        if not authorships:
            continue

        # Pour chaque authorship, vérifier si une institution a UCA dans le lineage
        uca_positions = set()
        for i, auth in enumerate(authorships):
            institutions = auth.get("institutions", [])
            for inst in institutions:
                lineage = inst.get("lineage", [])
                if UCA_OA_ID in lineage:
                    uca_positions.add(i)
                    break

        if uca_positions:
            # Marquer les publication_authors correspondants
            cur.execute("""
                UPDATE publication_authors
                SET is_uca_openalex = TRUE
                WHERE publication_id = %s
                  AND source = 'openalex'
                  AND author_position = ANY(%s)
            """, (pub_id, list(uca_positions)))
            marked += cur.rowcount

        processed += 1
        if processed % BATCH_SIZE == 0:
            conn.commit()
            elapsed = time.perf_counter() - t_start
            logger.info(f"  {processed}/{len(rows)} publis, {marked} auteurs marqués — {processed/elapsed:.0f} pub/s")

    conn.commit()
    elapsed = time.perf_counter() - t_start

    logger.info(f"\n=== Terminé en {elapsed:.1f}s ===")
    logger.info(f"  Publications traitées : {processed}")
    logger.info(f"  Auteurs marqués UCA OA : {marked}")

    # Stats de vérification
    cur.execute("""
        SELECT COUNT(*) FROM publication_authors
        WHERE source = 'openalex' AND is_uca_openalex = TRUE
    """)
    total_uca_oa = cur.fetchone()[0]
    logger.info(f"  Total auteurs is_uca_openalex=TRUE : {total_uca_oa}")

    conn.close()


if __name__ == "__main__":
    main()
