#!/usr/bin/env python3
"""
migrate_person_identifiers.py — Phase 2, étape 2.4
====================================================
Collecte les identifiants (ORCID, idHAL) depuis :
  - hal_authors (person_id résolu)
  - openalex_authors (person_id résolu)
  - legacy_authors (person_id résolu, pour rattraper d'éventuels manques)

Peuple person_identifiers avec déduplication (ON CONFLICT DO NOTHING).

Usage:
    python3 migrate_person_identifiers.py
    python3 migrate_person_identifiers.py --dry-run
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
            os.path.join(os.path.dirname(__file__), "migrate_person_identifiers.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


QUERIES = [
    ("ORCID depuis hal_authors", """
        INSERT INTO person_identifiers (person_id, id_type, id_value, source)
        SELECT DISTINCT person_id, 'orcid', orcid, 'hal'
        FROM hal_authors
        WHERE person_id IS NOT NULL AND orcid IS NOT NULL
        ON CONFLICT (id_type, id_value) DO NOTHING
    """),
    ("idHAL depuis hal_authors", """
        INSERT INTO person_identifiers (person_id, id_type, id_value, source)
        SELECT DISTINCT person_id, 'idhal', idhal, 'hal'
        FROM hal_authors
        WHERE person_id IS NOT NULL AND idhal IS NOT NULL
        ON CONFLICT (id_type, id_value) DO NOTHING
    """),
    ("ORCID depuis openalex_authors", """
        INSERT INTO person_identifiers (person_id, id_type, id_value, source)
        SELECT DISTINCT person_id, 'orcid', orcid, 'openalex'
        FROM openalex_authors
        WHERE person_id IS NOT NULL AND orcid IS NOT NULL
        ON CONFLICT (id_type, id_value) DO NOTHING
    """),
    ("ORCID depuis legacy_authors", """
        INSERT INTO person_identifiers (person_id, id_type, id_value, source)
        SELECT DISTINCT person_id, 'orcid', orcid, 'legacy'
        FROM legacy_authors
        WHERE person_id IS NOT NULL AND orcid IS NOT NULL
        ON CONFLICT (id_type, id_value) DO NOTHING
    """),
    ("idHAL depuis legacy_authors", """
        INSERT INTO person_identifiers (person_id, id_type, id_value, source)
        SELECT DISTINCT person_id, 'idhal', idhal, 'legacy'
        FROM legacy_authors
        WHERE person_id IS NOT NULL AND idhal IS NOT NULL
        ON CONFLICT (id_type, id_value) DO NOTHING
    """),
    ("openalex_id depuis legacy_authors", """
        INSERT INTO person_identifiers (person_id, id_type, id_value, source)
        SELECT DISTINCT person_id, 'openalex', openalex_id, 'legacy'
        FROM legacy_authors
        WHERE person_id IS NOT NULL AND openalex_id IS NOT NULL
        ON CONFLICT (id_type, id_value) DO NOTHING
    """),
]


def main():
    parser = argparse.ArgumentParser(
        description="Peuplement de person_identifiers depuis toutes les sources"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Rapport sans écriture en base")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        logger.info("=== Peuplement person_identifiers ===")
        if args.dry_run:
            logger.info("[MODE DRY RUN]")

        total_inserted = 0
        for label, query in QUERIES:
            cur.execute(query)
            count = cur.rowcount
            total_inserted += count
            logger.info(f"  {label} : {count} insérés")

        # Rapport conflits : même id_value mais person_id différent
        cur.execute("""
            SELECT pi.id_type, pi.id_value, pi.person_id AS existing_pid, pi.source,
                   src.person_id AS conflicting_pid, src.source AS conflicting_source
            FROM person_identifiers pi
            JOIN (
                SELECT person_id, 'orcid' AS id_type, orcid AS id_value, 'hal' AS source
                FROM hal_authors WHERE person_id IS NOT NULL AND orcid IS NOT NULL
                UNION ALL
                SELECT person_id, 'orcid', orcid, 'openalex'
                FROM openalex_authors WHERE person_id IS NOT NULL AND orcid IS NOT NULL
                UNION ALL
                SELECT person_id, 'idhal', idhal, 'hal'
                FROM hal_authors WHERE person_id IS NOT NULL AND idhal IS NOT NULL
            ) src ON pi.id_type = src.id_type AND pi.id_value = src.id_value
            WHERE pi.person_id != src.person_id
        """)
        conflicts = cur.fetchall()
        if conflicts:
            logger.warning(f"\n  {len(conflicts)} conflits détectés (même identifiant, person_id différent) :")
            for c in conflicts[:20]:
                logger.warning(f"    {c[0]}={c[1]} : person_id={c[2]} ({c[3]}) vs {c[4]} ({c[5]})")
            if len(conflicts) > 20:
                logger.warning(f"    ... et {len(conflicts) - 20} autres")

        if args.dry_run:
            conn.rollback()
            logger.info("\n[DRY RUN] Aucune modification enregistrée")
        else:
            conn.commit()

        # Stats finales (après commit ou rollback, on relit)
        if not args.dry_run:
            cur.execute("""
                SELECT id_type, COUNT(*), COUNT(DISTINCT person_id)
                FROM person_identifiers
                GROUP BY id_type
                ORDER BY id_type
            """)
            logger.info("\n--- person_identifiers ---")
            for row in cur.fetchall():
                logger.info(f"  {row[0]} : {row[1]} entrées, {row[2]} personnes distinctes")

            cur.execute("SELECT COUNT(*) FROM person_identifiers")
            logger.info(f"  Total : {cur.fetchone()[0]} entrées")

        logger.info(f"\n=== Terminé : {total_inserted} identifiants insérés ===")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
