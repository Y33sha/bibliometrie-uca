"""
Reconstruit la table authorships (table de vérité) à partir des authorships sources.

Étape 1 : Collecter toutes les paires (publication_id, person_id) des 3 sources
Étape 2 : Insérer les authorships manquantes
Étape 3 : Peupler les FK (hal_authorship_id, openalex_authorship_id, wos_authorship_id)
Étape 4 : Propager is_uca et structure_ids (identique à populate_uca_flags étape 4)

Usage:
    python rebuild_authorships.py              # exécuter
    python rebuild_authorships.py --dry-run    # dry-run
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "rebuild_authorships.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


def rebuild(cur):
    t0 = time.perf_counter()

    # ── Étape 1 : Insérer les authorships manquantes ──
    logger.info("Étape 1 : insertion des authorships manquantes...")

    cur.execute("""
        WITH all_pairs AS (
            SELECT DISTINCT hd.publication_id, ha.person_id
            FROM hal_authorships has
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            JOIN hal_authors ha ON ha.id = has.hal_author_id
            WHERE hd.publication_id IS NOT NULL AND ha.person_id IS NOT NULL

            UNION

            SELECT DISTINCT od.publication_id, oa.person_id
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
            WHERE od.publication_id IS NOT NULL AND oa.person_id IS NOT NULL

            UNION

            SELECT DISTINCT wd.publication_id, wa.person_id
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            JOIN wos_authors wa ON wa.id = was.wos_author_id
            WHERE wd.publication_id IS NOT NULL AND wa.person_id IS NOT NULL
        )
        INSERT INTO authorships (publication_id, person_id)
        SELECT ap.publication_id, ap.person_id
        FROM all_pairs ap
        WHERE NOT EXISTS (
            SELECT 1 FROM authorships a
            WHERE a.publication_id = ap.publication_id
              AND a.person_id = ap.person_id
        )
    """)
    inserted = cur.rowcount
    logger.info(f"  {inserted} authorships créées")

    # ── Étape 2 : Peupler les FK ──
    logger.info("Étape 2 : peuplement des FK...")

    # 2a. HAL
    cur.execute("""
        UPDATE authorships a
        SET hal_authorship_id = sub.has_id
        FROM (
            SELECT DISTINCT ON (hd.publication_id, ha.person_id)
                   hd.publication_id, ha.person_id, has.id AS has_id
            FROM hal_authorships has
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            JOIN hal_authors ha ON ha.id = has.hal_author_id
            WHERE hd.publication_id IS NOT NULL
              AND ha.person_id IS NOT NULL
            ORDER BY hd.publication_id, ha.person_id, has.id
        ) sub
        WHERE a.publication_id = sub.publication_id
          AND a.person_id = sub.person_id
          AND a.hal_authorship_id IS NULL
    """)
    hal_fk = cur.rowcount
    logger.info(f"  HAL FK : {hal_fk} liens")

    # 2b. OpenAlex
    cur.execute("""
        UPDATE authorships a
        SET openalex_authorship_id = sub.oas_id
        FROM (
            SELECT DISTINCT ON (od.publication_id, oa.person_id)
                   od.publication_id, oa.person_id, oas.id AS oas_id
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
            WHERE od.publication_id IS NOT NULL
              AND oa.person_id IS NOT NULL
            ORDER BY od.publication_id, oa.person_id, oas.id
        ) sub
        WHERE a.publication_id = sub.publication_id
          AND a.person_id = sub.person_id
          AND a.openalex_authorship_id IS NULL
    """)
    oa_fk = cur.rowcount
    logger.info(f"  OpenAlex FK : {oa_fk} liens")

    # 2c. WoS
    cur.execute("""
        UPDATE authorships a
        SET wos_authorship_id = sub.was_id
        FROM (
            SELECT DISTINCT ON (wd.publication_id, wa.person_id)
                   wd.publication_id, wa.person_id, was.id AS was_id
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            JOIN wos_authors wa ON wa.id = was.wos_author_id
            WHERE wd.publication_id IS NOT NULL
              AND wa.person_id IS NOT NULL
            ORDER BY wd.publication_id, wa.person_id, was.id
        ) sub
        WHERE a.publication_id = sub.publication_id
          AND a.person_id = sub.person_id
          AND a.wos_authorship_id IS NULL
    """)
    wos_fk = cur.rowcount
    logger.info(f"  WoS FK : {wos_fk} liens")

    # ── Étape 3 : author_position (prendre la première valeur non-null) ──
    logger.info("Étape 3 : mise à jour author_position...")

    cur.execute("""
        UPDATE authorships a
        SET author_position = COALESCE(has.author_position, oas.author_position, was.author_position)
        FROM authorships a2
        LEFT JOIN hal_authorships has ON has.id = a2.hal_authorship_id
        LEFT JOIN openalex_authorships oas ON oas.id = a2.openalex_authorship_id
        LEFT JOIN wos_authorships was ON was.id = a2.wos_authorship_id
        WHERE a.id = a2.id
          AND a.author_position IS NULL
          AND COALESCE(has.author_position, oas.author_position, was.author_position) IS NOT NULL
    """)
    pos_count = cur.rowcount
    logger.info(f"  {pos_count} positions mises à jour")

    # ── Étape 4 : is_corresponding ──
    logger.info("Étape 4 : mise à jour is_corresponding...")

    cur.execute("""
        UPDATE authorships a
        SET is_corresponding = was.is_corresponding
        FROM wos_authorships was
        WHERE was.id = a.wos_authorship_id
          AND a.is_corresponding IS NULL
          AND was.is_corresponding IS NOT NULL
    """)
    corr_count = cur.rowcount
    logger.info(f"  {corr_count} is_corresponding mises à jour")

    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")

    # Stats finales
    cur.execute("SELECT COUNT(*) FROM authorships")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM authorships WHERE hal_authorship_id IS NOT NULL")
    hal_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM authorships WHERE openalex_authorship_id IS NOT NULL")
    oa_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM authorships WHERE wos_authorship_id IS NOT NULL")
    wos_total = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM authorships
        WHERE hal_authorship_id IS NOT NULL AND openalex_authorship_id IS NOT NULL
    """)
    both = cur.fetchone()[0]

    logger.info(f"\n--- Statistiques authorships ---")
    logger.info(f"  Total                  : {total}")
    logger.info(f"  Avec HAL FK            : {hal_total}")
    logger.info(f"  Avec OpenAlex FK       : {oa_total}")
    logger.info(f"  Avec WoS FK            : {wos_total}")
    logger.info(f"  HAL + OpenAlex         : {both}")
    logger.info(f"  Sans aucune FK         : {total - hal_total - oa_total - wos_total + both}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Simuler sans modifier la base")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    rebuild(cur)

    if args.dry_run:
        conn.rollback()
        logger.info("DRY-RUN — aucune modification.")
    else:
        conn.commit()
        logger.info("COMMIT effectué.")

    conn.close()


if __name__ == "__main__":
    main()
