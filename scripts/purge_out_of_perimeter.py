"""
Purge des publications sans authorship in_perimeter.

Supprime les publications qui n'ont aucun authorship avec in_perimeter=true,
ainsi que toutes les données liées :
  - source_authorship_addresses
  - source_authorships
  - authorships
  - source_publications (+ détachement du staging)
  - apc_payments sans lab_structure_id
  - distinct_publications
  - publications

Le raw_data du staging est vidé pour les documents liés (la ligne staging
est conservée pour éviter un ré-import).

Les publications avec un APC lié à un labo UCA (lab_structure_id IS NOT NULL)
sont exclues de la purge.

Usage:
    python scripts/purge_out_of_perimeter.py              # dry-run
    python scripts/purge_out_of_perimeter.py --apply       # appliquer
"""

import argparse
import os

from psycopg2.extras import RealDictCursor

from db.connection import get_connection
from utils.log import setup_logger

logger = setup_logger("purge_oop", os.path.join(os.path.dirname(__file__), "../processing/logs"))


def run(dry_run=True):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Identifier les publications a purger
            cur.execute("""
                CREATE TEMP TABLE purge_pubs AS
                SELECT p.id FROM publications p
                WHERE NOT EXISTS (
                    SELECT 1 FROM authorships a
                    WHERE a.publication_id = p.id AND a.in_perimeter = true
                )
                AND NOT EXISTS (
                    SELECT 1 FROM apc_payments ap
                    WHERE ap.publication_id = p.id AND ap.lab_structure_id IS NOT NULL
                )
            """)
            cur.execute("SELECT count(*) AS cnt FROM purge_pubs")
            pub_count = cur.fetchone()["cnt"]
            logger.info("Publications a purger : %d", pub_count)

            if pub_count == 0:
                logger.info("Rien a purger.")
                conn.rollback()
                return

            # Source documents lies
            cur.execute("""
                CREATE TEMP TABLE purge_sd AS
                SELECT sd.id, sd.staging_id
                FROM source_publications sd
                WHERE sd.publication_id IN (SELECT id FROM purge_pubs)
            """)
            cur.execute("SELECT count(*) AS cnt FROM purge_sd")
            sd_count = cur.fetchone()["cnt"]

            # Source authorships lies
            cur.execute("""
                CREATE TEMP TABLE purge_sa AS
                SELECT sa.id FROM source_authorships sa
                WHERE sa.source_publication_id IN (SELECT id FROM purge_sd)
            """)
            cur.execute("SELECT count(*) AS cnt FROM purge_sa")
            sa_count = cur.fetchone()["cnt"]

            # Source authorship addresses
            cur.execute("""
                SELECT count(*) AS cnt FROM source_authorship_addresses saa
                WHERE saa.source_authorship_id IN (SELECT id FROM purge_sa)
            """)
            saa_count = cur.fetchone()["cnt"]

            # Authorships consolides
            cur.execute("""
                SELECT count(*) AS cnt FROM authorships a
                WHERE a.publication_id IN (SELECT id FROM purge_pubs)
            """)
            auth_count = cur.fetchone()["cnt"]

            # APC sans labo (ceux avec labo sont exclus par la condition)
            cur.execute("""
                SELECT count(*) AS cnt FROM apc_payments ap
                WHERE ap.publication_id IN (SELECT id FROM purge_pubs)
            """)
            apc_count = cur.fetchone()["cnt"]

            # Staging a vider
            cur.execute("""
                SELECT count(*) AS cnt FROM purge_sd WHERE staging_id IS NOT NULL
            """)
            staging_count = cur.fetchone()["cnt"]

            logger.info("  source_authorship_addresses : %d", saa_count)
            logger.info("  source_authorships          : %d", sa_count)
            logger.info("  authorships                 : %d", auth_count)
            logger.info("  apc_payments                : %d", apc_count)
            logger.info("  source_publications            : %d", sd_count)
            logger.info("  staging raw_data a vider    : %d", staging_count)
            logger.info("  publications                : %d", pub_count)

            if dry_run:
                logger.info("DRY-RUN -- aucune modification")
                conn.rollback()
                return

            # Suppression dans l'ordre des FK

            cur.execute("""
                DELETE FROM source_authorship_addresses
                WHERE source_authorship_id IN (SELECT id FROM purge_sa)
            """)
            logger.info("  source_authorship_addresses supprimées : %d", cur.rowcount)

            cur.execute("""
                DELETE FROM source_authorships
                WHERE source_publication_id IN (SELECT id FROM purge_sd)
            """)
            logger.info("  source_authorships supprimées : %d", cur.rowcount)

            cur.execute("""
                DELETE FROM authorships
                WHERE publication_id IN (SELECT id FROM purge_pubs)
            """)
            logger.info("  authorships supprimées : %d", cur.rowcount)

            cur.execute("""
                DELETE FROM apc_payments
                WHERE publication_id IN (SELECT id FROM purge_pubs)
            """)
            logger.info("  apc_payments supprimées : %d", cur.rowcount)

            # Vider raw_data du staging (conserver la ligne pour eviter re-import)
            cur.execute("""
                UPDATE staging SET raw_data = '{}'::jsonb
                WHERE id IN (SELECT staging_id FROM purge_sd WHERE staging_id IS NOT NULL)
                  AND raw_data != '{}'::jsonb
            """)
            logger.info("  staging raw_data videes : %d", cur.rowcount)

            cur.execute("""
                DELETE FROM distinct_publications
                WHERE pub_id_a IN (SELECT id FROM purge_pubs)
                   OR pub_id_b IN (SELECT id FROM purge_pubs)
            """)
            logger.info("  distinct_publications supprimées : %d", cur.rowcount)

            cur.execute("""
                DELETE FROM source_publications
                WHERE publication_id IN (SELECT id FROM purge_pubs)
            """)
            logger.info("  source_publications supprimées : %d", cur.rowcount)

            cur.execute("""
                DELETE FROM publications
                WHERE id IN (SELECT id FROM purge_pubs)
            """)
            logger.info("  publications supprimées : %d", cur.rowcount)

            conn.commit()
            logger.info("Purge terminée avec succès.")

    except Exception:
        conn.rollback()
        logger.exception("Erreur lors de la purge")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge des publications hors perimetre")
    parser.add_argument("--apply", action="store_true", help="Appliquer les suppressions")
    args = parser.parse_args()
    run(dry_run=not args.apply)
