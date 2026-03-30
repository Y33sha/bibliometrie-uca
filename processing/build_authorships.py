"""
Construit la table authorships (table de vérité) à partir des authorships sources.

Étape 1 : Insérer les authorships manquantes (paires publication_id, person_id)
Étape 2 : Peupler les FK (hal_authorship_id, openalex_authorship_id, wos_authorship_id)
Étape 3 : Propager author_position et is_corresponding
Étape 4 : Propager is_uca et structure_ids (union des 3 sources)

Usage:
    python build_authorships.py              # exécuter
    python build_authorships.py --dry-run    # dry-run
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
            os.path.join(os.path.dirname(__file__), "build_authorships.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


def build(cur):
    t0 = time.perf_counter()

    # ── Étape 1 : Insérer les authorships manquantes ──
    logger.info("Étape 1 : insertion des authorships manquantes...")

    cur.execute("""
        WITH all_pairs AS (
            SELECT DISTINCT hd.publication_id, has.person_id
            FROM hal_authorships has
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            WHERE hd.publication_id IS NOT NULL AND has.person_id IS NOT NULL

            UNION

            SELECT DISTINCT od.publication_id, oas.person_id
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            WHERE od.publication_id IS NOT NULL AND oas.person_id IS NOT NULL

            UNION

            SELECT DISTINCT wd.publication_id, was.person_id
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            WHERE wd.publication_id IS NOT NULL AND was.person_id IS NOT NULL
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
            SELECT DISTINCT ON (hd.publication_id, has.person_id)
                   hd.publication_id, has.person_id, has.id AS has_id
            FROM hal_authorships has
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            WHERE hd.publication_id IS NOT NULL
              AND has.person_id IS NOT NULL
            ORDER BY hd.publication_id, has.person_id, has.id
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
            SELECT DISTINCT ON (od.publication_id, oas.person_id)
                   od.publication_id, oas.person_id, oas.id AS oas_id
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            WHERE od.publication_id IS NOT NULL
              AND oas.person_id IS NOT NULL
            ORDER BY od.publication_id, oas.person_id, oas.id
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
            SELECT DISTINCT ON (wd.publication_id, was.person_id)
                   wd.publication_id, was.person_id, was.id AS was_id
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            WHERE wd.publication_id IS NOT NULL
              AND was.person_id IS NOT NULL
            ORDER BY wd.publication_id, was.person_id, was.id
        ) sub
        WHERE a.publication_id = sub.publication_id
          AND a.person_id = sub.person_id
          AND a.wos_authorship_id IS NULL
    """)
    wos_fk = cur.rowcount
    logger.info(f"  WoS FK : {wos_fk} liens")

    # ── Étape 3 : author_position et is_corresponding ──
    logger.info("Étape 3 : author_position et is_corresponding...")

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

    # ── Étape 4 : Propagation is_uca et structure_ids ──
    logger.info("Étape 4 : propagation is_uca et structure_ids...")

    # Reset toutes les authorships
    cur.execute("UPDATE authorships SET is_uca = FALSE, structure_ids = NULL")
    reset_count = cur.rowcount
    logger.info(f"  Reset {reset_count} authorships")

    # 4a. Depuis HAL (exclut peer_review : auteurs = ceux de l'article reviewé, pas du review)
    cur.execute("""
        WITH uca_perimeter AS (
            SELECT s.id FROM structures s WHERE s.code = 'uca'
            UNION
            SELECT sr.child_id FROM structure_relations sr
            JOIN structures s ON s.id = sr.parent_id
            WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
        ),
        hal_data AS (
            SELECT hd.publication_id,
                   has.person_id,
                   array_agg(DISTINCT sid) AS all_struct_ids,
                   bool_or(sid IN (SELECT id FROM uca_perimeter)) AS has_uca
            FROM hal_authorships has
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            JOIN publications pub ON pub.id = hd.publication_id,
            LATERAL unnest(has.structure_ids) AS sid
            WHERE has.structure_ids IS NOT NULL
              AND hd.publication_id IS NOT NULL
              AND has.person_id IS NOT NULL
              AND pub.doc_type != 'peer_review'
            GROUP BY hd.publication_id, has.person_id
        )
        UPDATE authorships a
        SET structure_ids = hd.all_struct_ids,
            is_uca = hd.has_uca,
            updated_at = now()
        FROM hal_data hd
        WHERE a.publication_id = hd.publication_id
          AND a.person_id = hd.person_id
    """)
    hal_uca = cur.rowcount
    logger.info(f"  {hal_uca} authorships mises à jour depuis HAL")

    # 4b. Depuis OpenAlex (union avec existant, exclut peer_review)
    cur.execute("""
        WITH oa_data AS (
            SELECT od.publication_id,
                   oas.person_id,
                   oas.structure_ids AS struct_ids,
                   oas.is_uca AS src_is_uca
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN publications pub ON pub.id = od.publication_id
            WHERE oas.structure_ids IS NOT NULL
              AND od.publication_id IS NOT NULL
              AND oas.person_id IS NOT NULL
              AND pub.doc_type != 'peer_review'
        )
        UPDATE authorships a
        SET structure_ids = (
                SELECT array_agg(DISTINCT x)
                FROM unnest(COALESCE(a.structure_ids, '{}') || od.struct_ids) AS x
            ),
            is_uca = a.is_uca OR od.src_is_uca,
            updated_at = now()
        FROM oa_data od
        WHERE a.publication_id = od.publication_id
          AND a.person_id = od.person_id
    """)
    oa_uca = cur.rowcount
    logger.info(f"  {oa_uca} authorships mises à jour depuis OpenAlex")

    # 4c. Depuis WoS (union avec existant, exclut peer_review)
    cur.execute("""
        WITH wos_data AS (
            SELECT wd.publication_id,
                   was.person_id,
                   was.structure_ids AS struct_ids,
                   was.is_uca AS src_is_uca
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            JOIN publications pub ON pub.id = wd.publication_id
            WHERE was.structure_ids IS NOT NULL
              AND wd.publication_id IS NOT NULL
              AND was.person_id IS NOT NULL
              AND pub.doc_type != 'peer_review'
        )
        UPDATE authorships a
        SET structure_ids = (
                SELECT array_agg(DISTINCT x)
                FROM unnest(COALESCE(a.structure_ids, '{}') || wd.struct_ids) AS x
            ),
            is_uca = a.is_uca OR wd.src_is_uca,
            updated_at = now()
        FROM wos_data wd
        WHERE a.publication_id = wd.publication_id
          AND a.person_id = wd.person_id
    """)
    wos_uca = cur.rowcount
    logger.info(f"  {wos_uca} authorships mises à jour depuis WoS")

    cur.execute("SELECT COUNT(*) FROM authorships WHERE is_uca = TRUE")
    total_uca = cur.fetchone()[0]
    logger.info(f"  Total authorships is_uca=TRUE : {total_uca}")

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
    logger.info(f"  dont is_uca            : {total_uca}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Simuler sans modifier la base")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    build(cur)

    if args.dry_run:
        conn.rollback()
        logger.info("DRY-RUN — aucune modification.")
    else:
        conn.commit()
        logger.info("COMMIT effectué.")

    conn.close()


if __name__ == "__main__":
    main()
