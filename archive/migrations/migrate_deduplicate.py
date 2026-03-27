#!/usr/bin/env python3
"""
migrate_deduplicate.py — Phase 2, étape 2.5
=============================================
Relie hal_documents et openalex_documents aux publications existantes :
  1. Par DOI
  2. Par source_id (via publication_sources)
  3. Par titre normalisé + année

Usage:
    python3 migrate_deduplicate.py
    python3 migrate_deduplicate.py --dry-run
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "migrate_deduplicate.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


def link_hal(cur) -> dict:
    stats = {}

    # 1. Par DOI
    cur.execute("""
        UPDATE hal_documents hd
        SET publication_id = p.id
        FROM publications p
        WHERE hd.doi IS NOT NULL
          AND hd.doi = p.doi
          AND hd.publication_id IS NULL
    """)
    stats["hal_doi"] = cur.rowcount
    logger.info(f"  HAL par DOI : {stats['hal_doi']}")

    # 2. Par source_id (publication_sources)
    cur.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'publication_sources' AND table_type = 'BASE TABLE'
    """)
    if cur.fetchone():
        cur.execute("""
            UPDATE hal_documents hd
            SET publication_id = ps.publication_id
            FROM publication_sources ps
            WHERE ps.source = 'hal'
              AND ps.source_id = hd.halid
              AND hd.publication_id IS NULL
        """)
        stats["hal_source"] = cur.rowcount
        logger.info(f"  HAL par publication_sources : {stats['hal_source']}")
    else:
        stats["hal_source"] = 0
        logger.info("  HAL par publication_sources : table absente, skippé")

    # 3. Par titre normalisé + année
    cur.execute("""
        UPDATE hal_documents hd
        SET publication_id = sub.pub_id
        FROM (
            SELECT DISTINCT ON (hd2.id) hd2.id AS hd_id, p.id AS pub_id
            FROM hal_documents hd2
            JOIN publications p
              ON hd2.pub_year = p.pub_year
              AND p.title_normalized IS NOT NULL
              AND p.title_normalized != ''
              AND p.title_normalized = lower(regexp_replace(
                  translate(hd2.title,
                      'àâäéèêëïîôùûüÿçÀÂÄÉÈÊËÏÎÔÙÛÜŸÇ',
                      'aaaeeeeiioouuycAAÄEEEEIIOOUUUYC'),
                  '[^a-zA-Z0-9 ]', '', 'g'
              ))
            WHERE hd2.publication_id IS NULL
              AND hd2.pub_year IS NOT NULL
        ) sub
        WHERE hd.id = sub.hd_id
    """)
    stats["hal_title"] = cur.rowcount
    logger.info(f"  HAL par titre+année : {stats['hal_title']}")

    return stats


def link_openalex(cur) -> dict:
    stats = {}

    # 1. Par DOI
    cur.execute("""
        UPDATE openalex_documents od
        SET publication_id = p.id
        FROM publications p
        WHERE od.doi IS NOT NULL
          AND od.doi = p.doi
          AND od.publication_id IS NULL
    """)
    stats["oa_doi"] = cur.rowcount
    logger.info(f"  OpenAlex par DOI : {stats['oa_doi']}")

    # 2. Par source_id (publication_sources)
    cur.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'publication_sources' AND table_type = 'BASE TABLE'
    """)
    if cur.fetchone():
        cur.execute("""
            UPDATE openalex_documents od
            SET publication_id = ps.publication_id
            FROM publication_sources ps
            WHERE ps.source = 'openalex'
              AND ps.source_id = od.openalex_id
              AND od.publication_id IS NULL
        """)
        stats["oa_source"] = cur.rowcount
        logger.info(f"  OpenAlex par publication_sources : {stats['oa_source']}")
    else:
        stats["oa_source"] = 0
        logger.info("  OpenAlex par publication_sources : table absente, skippé")

    # 3. Par titre normalisé + année
    cur.execute("""
        UPDATE openalex_documents od
        SET publication_id = sub.pub_id
        FROM (
            SELECT DISTINCT ON (od2.id) od2.id AS od_id, p.id AS pub_id
            FROM openalex_documents od2
            JOIN publications p
              ON od2.pub_year = p.pub_year
              AND p.title_normalized IS NOT NULL
              AND p.title_normalized != ''
              AND p.title_normalized = lower(regexp_replace(
                  translate(od2.title,
                      'àâäéèêëïîôùûüÿçÀÂÄÉÈÊËÏÎÔÙÛÜŸÇ',
                      'aaaeeeeiioouuycAAÄEEEEIIOOUUUYC'),
                  '[^a-zA-Z0-9 ]', '', 'g'
              ))
            WHERE od2.publication_id IS NULL
              AND od2.pub_year IS NOT NULL
        ) sub
        WHERE od.id = sub.od_id
    """)
    stats["oa_title"] = cur.rowcount
    logger.info(f"  OpenAlex par titre+année : {stats['oa_title']}")

    return stats


def cross_link(cur):
    """Relie hal_documents ↔ openalex_documents entre eux via publication_id commun."""
    logger.info("\n--- Croisement HAL ↔ OpenAlex ---")

    cur.execute("""
        SELECT COUNT(*) FROM hal_documents hd
        JOIN openalex_documents od ON hd.publication_id = od.publication_id
        WHERE hd.publication_id IS NOT NULL
    """)
    shared = cur.fetchone()[0]
    logger.info(f"  Publications communes (via publication_id) : {shared}")


def report(cur):
    logger.info("\n--- Rapport ---")

    for table, label in [("hal_documents", "HAL"), ("openalex_documents", "OpenAlex")]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        total = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE publication_id IS NOT NULL")
        linked = cur.fetchone()[0]
        orphans = total - linked
        pct = (linked / total * 100) if total > 0 else 0
        logger.info(f"  {label} : {linked}/{total} reliés ({pct:.1f}%), {orphans} orphelins")

    # Orphelins sans DOI (les plus difficiles à relier)
    for table, label in [("hal_documents", "HAL"), ("openalex_documents", "OpenAlex")]:
        cur.execute(f"""
            SELECT COUNT(*) FROM {table}
            WHERE publication_id IS NULL AND doi IS NULL
        """)
        no_doi = cur.fetchone()[0]
        cur.execute(f"""
            SELECT COUNT(*) FROM {table}
            WHERE publication_id IS NULL AND doi IS NOT NULL
        """)
        has_doi = cur.fetchone()[0]
        logger.info(f"  {label} orphelins : {has_doi} avec DOI, {no_doi} sans DOI")


def main():
    parser = argparse.ArgumentParser(
        description="Déduplication : liaison documents sources → publications"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Rapport sans écriture en base")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        logger.info("=== Déduplication publications ===")
        if args.dry_run:
            logger.info("[MODE DRY RUN]")

        logger.info("\n--- HAL ---")
        hal_stats = link_hal(cur)

        logger.info("\n--- OpenAlex ---")
        oa_stats = link_openalex(cur)

        if args.dry_run:
            conn.rollback()
            logger.info("\n[DRY RUN] Aucune modification enregistrée")
        else:
            conn.commit()

        cross_link(cur)
        report(cur)

        # Résumé
        hal_total = sum(hal_stats.values())
        oa_total = sum(oa_stats.values())
        logger.info(f"\n=== Résumé : {hal_total} HAL + {oa_total} OpenAlex reliés ===")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
