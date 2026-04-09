"""
Construit la table authorships (table de vérité) à partir des authorships sources.

Étape 1 : Insérer les authorships manquantes (paires publication_id, person_id)
Étape 2 : Peupler les FK (hal_authorship_id, openalex_authorship_id, wos_authorship_id)
Étape 3 : Propager author_position et is_corresponding
Étape 4 : Propager in_perimeter et structure_ids (union des sources)

Usage:
    python build_authorships.py              # exécuter
    python build_authorships.py --dry-run    # dry-run
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.log import setup_logger

logger = setup_logger("build_authorships", os.path.join(os.path.dirname(__file__), "logs"))


def build(cur):
    t0 = time.perf_counter()

    # ── Étape 1 : Insérer les authorships manquantes ──
    logger.info("Étape 1 : insertion des authorships manquantes...")

    cur.execute("""
        WITH all_pairs AS (
            SELECT DISTINCT sd.publication_id, sa.person_id
            FROM source_authorships sa
            JOIN source_documents sd ON sd.id = sa.source_document_id
            JOIN v_active_publications vap ON vap.id = sd.publication_id
            WHERE sa.person_id IS NOT NULL AND NOT sa.excluded
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

    FK_QUERIES = [
        ("HAL", "hal", "hal_authorship_id"),
        ("OpenAlex", "openalex", "openalex_authorship_id"),
        ("WoS", "wos", "wos_authorship_id"),
        ("ScanR", "scanr", "scanr_authorship_id"),
    ]

    for source_name, source_value, fk_col in FK_QUERIES:
        cur.execute(f"""
            UPDATE authorships a
            SET {fk_col} = sub.sa_id
            FROM (
                SELECT DISTINCT ON (sd.publication_id, sa.person_id)
                       sd.publication_id, sa.person_id, sa.id AS sa_id
                FROM source_authorships sa
                JOIN source_documents sd ON sd.id = sa.source_document_id
                WHERE sa.source = %s
                  AND sd.publication_id IS NOT NULL
                  AND sa.person_id IS NOT NULL
                  AND NOT sa.excluded
                ORDER BY sd.publication_id, sa.person_id, sa.id
            ) sub
            WHERE a.publication_id = sub.publication_id
              AND a.person_id = sub.person_id
              AND a.{fk_col} IS NULL
        """, (source_value,))
        logger.info(f"  {source_name} FK : {cur.rowcount} liens")

    # ── Étape 3 : author_position et is_corresponding ──
    logger.info("Étape 3 : author_position et is_corresponding...")

    cur.execute("""
        UPDATE authorships a
        SET author_position = COALESCE(sa_hal.author_position, sa_oa.author_position, sa_scanr.author_position, sa_wos.author_position)
        FROM authorships a2
        LEFT JOIN source_authorships sa_hal ON sa_hal.id = a2.hal_authorship_id
        LEFT JOIN source_authorships sa_oa ON sa_oa.id = a2.openalex_authorship_id
        LEFT JOIN source_authorships sa_scanr ON sa_scanr.id = a2.scanr_authorship_id
        LEFT JOIN source_authorships sa_wos ON sa_wos.id = a2.wos_authorship_id
        WHERE a.id = a2.id
          AND a.author_position IS NULL
          AND COALESCE(sa_hal.author_position, sa_oa.author_position, sa_scanr.author_position, sa_wos.author_position) IS NOT NULL
    """)
    pos_count = cur.rowcount
    logger.info(f"  {pos_count} positions mises à jour")

    cur.execute("""
        UPDATE authorships a
        SET is_corresponding = COALESCE(sa_wos.is_corresponding, sa_oa.is_corresponding, sa_hal.is_corresponding)
        FROM authorships a2
        LEFT JOIN source_authorships sa_wos ON sa_wos.id = a2.wos_authorship_id
        LEFT JOIN source_authorships sa_oa ON sa_oa.id = a2.openalex_authorship_id
        LEFT JOIN source_authorships sa_hal ON sa_hal.id = a2.hal_authorship_id
        WHERE a.id = a2.id
          AND a.is_corresponding IS NULL
          AND COALESCE(sa_wos.is_corresponding, sa_oa.is_corresponding, sa_hal.is_corresponding) IS NOT NULL
    """)
    corr_count = cur.rowcount
    logger.info(f"  {corr_count} is_corresponding mises à jour")

    # ── Étape 4 : Propagation in_perimeter et structure_ids ──
    # Les sources ont déjà in_perimeter et structure_ids peuplés par
    # populate_affiliations.py → on fait l'union des sources.
    logger.info("Étape 4 : propagation in_perimeter et structure_ids...")

    # Reset toutes les authorships
    cur.execute("UPDATE authorships SET in_perimeter = FALSE, structure_ids = NULL")
    reset_count = cur.rowcount
    logger.info(f"  Reset {reset_count} authorships")

    # Union des structure_ids et OR des in_perimeter par source
    for source_name, source_value in [("HAL", "hal"), ("OpenAlex", "openalex"),
                                       ("WoS", "wos"), ("ScanR", "scanr")]:
        cur.execute("""
            WITH src_data AS (
                SELECT sd.publication_id, sa.person_id,
                       sa.structure_ids AS struct_ids, sa.in_perimeter AS src_in_perimeter
                FROM source_authorships sa
                JOIN source_documents sd ON sd.id = sa.source_document_id
                JOIN v_active_publications vap ON vap.id = sd.publication_id
                WHERE sa.source = %s
                  AND sa.structure_ids IS NOT NULL
                  AND sa.person_id IS NOT NULL
                  AND NOT sa.excluded
            )
            UPDATE authorships a
            SET structure_ids = (
                    SELECT array_agg(DISTINCT x)
                    FROM unnest(COALESCE(a.structure_ids, '{}'::int[]) || sd.struct_ids) AS x
                ),
                in_perimeter = a.in_perimeter OR sd.src_in_perimeter,
                updated_at = now()
            FROM src_data sd
            WHERE a.publication_id = sd.publication_id
              AND a.person_id = sd.person_id
        """, (source_value,))
        logger.info(f"  {source_name} : {cur.rowcount} authorships mises à jour")

    cur.execute("SELECT COUNT(*) FROM authorships WHERE in_perimeter = TRUE")
    total_uca = cur.fetchone()[0]
    logger.info(f"  Total authorships in_perimeter=TRUE : {total_uca}")

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
    cur.execute("SELECT COUNT(*) FROM authorships WHERE scanr_authorship_id IS NOT NULL")
    scanr_total = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM authorships
        WHERE hal_authorship_id IS NOT NULL AND openalex_authorship_id IS NOT NULL
    """)
    both = cur.fetchone()[0]

    logger.info(f"\n--- Statistiques authorships ---")
    logger.info(f"  Total                  : {total}")
    logger.info(f"  Avec HAL FK            : {hal_total}")
    logger.info(f"  Avec OpenAlex FK       : {oa_total}")
    logger.info(f"  Avec ScanR FK          : {scanr_total}")
    logger.info(f"  Avec WoS FK            : {wos_total}")
    logger.info(f"  HAL + OpenAlex         : {both}")
    logger.info(f"  dont in_perimeter      : {total_uca}")


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
