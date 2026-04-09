"""
Recalcule publications.countries à partir des 3 sources.

Sources des pays :
  - HAL : source_documents.countries (via hal_structures.country)
  - OpenAlex : addresses.countries (via openalex_authorship_addresses)
  - WoS : addresses.countries (via wos_authorship_addresses)

On n'utilise PAS les countries des source_documents OpenAlex (données staging OA non fiables).

Usage:
    python refresh_publication_countries.py              # recalculer
    python refresh_publication_countries.py --stats      # stats uniquement
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.log import setup_logger

logger = setup_logger("refresh_publication_countries", os.path.join(os.path.dirname(__file__), "logs"))


REFRESH_QUERY = """
    UPDATE publications p
    SET countries = sub.all_countries
    FROM (
        SELECT pub_id,
               array_agg(DISTINCT c ORDER BY c) AS all_countries
        FROM (
            -- HAL : pays des structures HAL
            SELECT sd.publication_id AS pub_id, unnest(sd.countries) AS c
            FROM source_documents sd
            WHERE sd.source = 'hal' AND sd.countries IS NOT NULL

            UNION ALL

            -- OpenAlex : pays des adresses résolues
            SELECT sd.publication_id AS pub_id, unnest(a.countries) AS c
            FROM openalex_authorship_addresses oaa
            JOIN addresses a ON a.id = oaa.address_id
            JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
            JOIN source_documents sd ON sd.id = oas.source_document_id
            WHERE a.countries IS NOT NULL AND sd.publication_id IS NOT NULL

            UNION ALL

            -- WoS : pays des adresses résolues
            SELECT sd.publication_id AS pub_id, unnest(a.countries) AS c
            FROM wos_authorship_addresses waa
            JOIN addresses a ON a.id = waa.address_id
            JOIN wos_authorships was ON was.id = waa.wos_authorship_id
            JOIN source_documents sd ON sd.id = was.source_document_id
            WHERE a.countries IS NOT NULL AND sd.publication_id IS NOT NULL
        ) src
        GROUP BY pub_id
    ) sub
    WHERE p.id = sub.pub_id
      AND p.countries IS DISTINCT FROM sub.all_countries
"""


def refresh_hal_document_countries(cur):
    """Étape préalable : propager hal_structures.country → source_documents.countries (HAL).

    Pour chaque document HAL, collecte les pays des structures de ses auteurs
    (via hal_authorships.hal_struct_ids → hal_structures.country).
    """
    cur.execute("""
        UPDATE source_documents sd
        SET countries = sub.doc_countries
        FROM (
            SELECT has.source_document_id,
                   array_agg(DISTINCT hs.country ORDER BY hs.country) AS doc_countries
            FROM hal_authorships has,
                 LATERAL unnest(has.hal_struct_ids) AS hsid(val)
            JOIN hal_structures hs ON hs.hal_struct_id = hsid.val
            WHERE hs.country IS NOT NULL
            GROUP BY has.source_document_id
        ) sub
        WHERE sd.id = sub.source_document_id
          AND sd.source = 'hal'
          AND sd.countries IS DISTINCT FROM sub.doc_countries
    """)
    updated = cur.rowcount
    logger.info(f"HAL documents countries : {updated} mis à jour")
    return updated


def refresh(cur):
    t0 = time.perf_counter()

    # 1. D'abord propager les pays HAL (structures → documents)
    refresh_hal_document_countries(cur)

    # 2. Puis recalculer les pays des publications (union des 3 sources)
    cur.execute(REFRESH_QUERY)
    updated = cur.rowcount
    elapsed = time.perf_counter() - t0
    logger.info(f"{updated} publications mises à jour en {elapsed:.1f}s")
    return updated


def show_stats(cur):
    cur.execute("SELECT COUNT(*) FROM publications")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM publications WHERE countries IS NOT NULL")
    with_countries = cur.fetchone()[0]
    cur.execute("""
        SELECT unnest(countries) AS c, COUNT(*) AS n
        FROM publications
        WHERE countries IS NOT NULL
        GROUP BY c ORDER BY n DESC LIMIT 10
    """)
    top = cur.fetchall()

    logger.info(f"\n--- Statistiques pays ---")
    logger.info(f"  Publications totales       : {total}")
    logger.info(f"  Avec pays                  : {with_countries} ({100*with_countries//max(total,1)}%)")
    logger.info(f"  Sans pays                  : {total - with_countries}")
    if top:
        logger.info(f"  Top 10 pays :")
        for row in top:
            logger.info(f"    {row[0]} : {row[1]}")


def main():
    parser = argparse.ArgumentParser(description="Recalcul des pays des publications")
    parser.add_argument("--stats", action="store_true", help="Stats uniquement")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.stats:
        show_stats(cur)
        conn.close()
        return

    refresh(cur)
    conn.commit()
    show_stats(cur)
    conn.close()


if __name__ == "__main__":
    main()
