"""
Recalcule publications.countries à partir des 3 sources.

Trois étapes :
  1. HAL : source_structures.country → source_publications.countries
  2. OA/WoS/ScanR : addresses.countries → source_publications.countries
  3. Union de tous les source_publications.countries → publications.countries

Usage:
    python refresh_publication_countries.py              # recalculer
    python refresh_publication_countries.py --stats      # stats uniquement
"""

import argparse
import os
import time

from db.connection import get_connection
from utils.log import setup_logger

logger = setup_logger(
    "refresh_publication_countries", os.path.join(os.path.dirname(__file__), "logs")
)


REFRESH_QUERY = """
    UPDATE publications p
    SET countries = sub.all_countries
    FROM (
        SELECT sd.publication_id AS pub_id,
               array_agg(DISTINCT c ORDER BY c) AS all_countries
        FROM source_publications sd,
        LATERAL unnest(sd.countries) AS c
        WHERE sd.countries IS NOT NULL
          AND sd.publication_id IS NOT NULL
        GROUP BY sd.publication_id
    ) sub
    WHERE p.id = sub.pub_id
      AND p.countries IS DISTINCT FROM sub.all_countries
"""


def refresh_hal_document_countries(cur):
    """Étape préalable : propager source_structures.country → source_publications.countries (HAL).

    Pour chaque document HAL, collecte les pays des structures de ses auteurs
    (via source_authorships.source_struct_ids → source_structures.country).
    """
    cur.execute("""
        UPDATE source_publications sd
        SET countries = sub.doc_countries
        FROM (
            SELECT sa.source_publication_id,
                   array_agg(DISTINCT ss.country ORDER BY ss.country) AS doc_countries
            FROM source_authorships sa,
                 LATERAL unnest(sa.source_struct_ids) AS ssid(val)
            JOIN source_structures ss ON ss.id = ssid.val
            WHERE sa.source = 'hal'
              AND ss.country IS NOT NULL
            GROUP BY sa.source_publication_id
        ) sub
        WHERE sd.id = sub.source_publication_id
          AND sd.source = 'hal'
          AND sd.countries IS DISTINCT FROM sub.doc_countries
    """)
    updated = cur.rowcount
    logger.info(f"HAL documents countries : {updated} mis à jour")
    return updated


def refresh_address_document_countries(cur):
    """Propager addresses.countries → source_publications.countries (OA, WoS, ScanR).

    Pour chaque document non-HAL, collecte les pays des adresses de ses auteurs
    (via source_authorship_addresses → addresses.countries).
    """
    cur.execute("""
        UPDATE source_publications sd
        SET countries = sub.doc_countries
        FROM (
            SELECT sa.source_publication_id,
                   array_agg(DISTINCT c::text ORDER BY c::text) AS doc_countries
            FROM source_authorships sa
            JOIN source_authorship_addresses saa ON saa.source_authorship_id = sa.id
            JOIN addresses a ON a.id = saa.address_id,
            LATERAL unnest(a.countries) AS c
            WHERE TRUE  -- toutes les sources utilisent les adresses
              AND a.countries IS NOT NULL
            GROUP BY sa.source_publication_id
        ) sub
        WHERE sd.id = sub.source_publication_id
          AND sd.countries IS DISTINCT FROM sub.doc_countries
    """)
    updated = cur.rowcount
    logger.info(f"OA/WoS/ScanR documents countries : {updated} mis à jour")
    return updated


def refresh(cur):
    t0 = time.perf_counter()

    # 1. Propager les pays HAL (structures → documents)
    refresh_hal_document_countries(cur)

    # 2. Propager les pays OA/WoS/ScanR (adresses → documents)
    refresh_address_document_countries(cur)

    # 3. Recalculer les pays des publications (union de toutes les sources)
    cur.execute(REFRESH_QUERY)
    updated = cur.rowcount
    elapsed = time.perf_counter() - t0
    logger.info(f"{updated} publications mises à jour en {elapsed:.1f}s")
    return updated


def main():
    parser = argparse.ArgumentParser(description="Recalcul des pays des publications")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    refresh(cur)
    conn.commit()
    logger.info("Terminé")
    conn.close()


if __name__ == "__main__":
    main()
