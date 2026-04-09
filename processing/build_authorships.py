"""
Construit la table authorships (table de vérité) à partir des authorships sources.

Étape 1 : Insérer les authorships manquantes (paires publication_id, person_id)
Étape 2 : Peupler les FK (source_authorships.authorship_id → authorships.id)
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

    # ── Étape 2 : Peupler les FK (source_authorships.authorship_id) ──
    logger.info("Étape 2 : peuplement des FK (source_authorships → authorships)...")

    FK_SOURCES = [
        ("HAL", "hal"),
        ("OpenAlex", "openalex"),
        ("WoS", "wos"),
        ("ScanR", "scanr"),
    ]

    for source_name, source_value in FK_SOURCES:
        cur.execute("""
            UPDATE source_authorships sa
            SET authorship_id = a.id
            FROM source_documents sd
            JOIN authorships a ON a.publication_id = sd.publication_id
            WHERE sd.id = sa.source_document_id
              AND sa.source = %s
              AND sa.person_id IS NOT NULL
              AND a.person_id = sa.person_id
              AND NOT sa.excluded
              AND sa.authorship_id IS NULL
        """, (source_value,))
        logger.info(f"  {source_name} FK : {cur.rowcount} liens")

    # ── Étape 3 : author_position et is_corresponding ──
    logger.info("Étape 3 : author_position et is_corresponding...")

    cur.execute("""
        UPDATE authorships a
        SET author_position = sub.pos
        FROM (
            SELECT sa.authorship_id,
                   (array_agg(sa.author_position ORDER BY
                       CASE sa.source WHEN 'hal' THEN 1 WHEN 'openalex' THEN 2 WHEN 'scanr' THEN 3 WHEN 'wos' THEN 4 END
                   ))[1] AS pos
            FROM source_authorships sa
            WHERE sa.authorship_id IS NOT NULL
              AND sa.author_position IS NOT NULL
              AND NOT sa.excluded
            GROUP BY sa.authorship_id
        ) sub
        WHERE a.id = sub.authorship_id
          AND a.author_position IS NULL
    """)
    pos_count = cur.rowcount
    logger.info(f"  {pos_count} positions mises à jour")

    cur.execute("""
        UPDATE authorships a
        SET is_corresponding = sub.corr
        FROM (
            SELECT sa.authorship_id,
                   (array_agg(sa.is_corresponding ORDER BY
                       CASE sa.source WHEN 'wos' THEN 1 WHEN 'openalex' THEN 2 WHEN 'hal' THEN 3 END
                   ))[1] AS corr
            FROM source_authorships sa
            WHERE sa.authorship_id IS NOT NULL
              AND sa.is_corresponding IS NOT NULL
              AND NOT sa.excluded
            GROUP BY sa.authorship_id
        ) sub
        WHERE a.id = sub.authorship_id
          AND a.is_corresponding IS NULL
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
    cur.execute("SELECT COUNT(*) FROM source_authorships WHERE authorship_id IS NOT NULL AND source = 'hal'")
    hal_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM source_authorships WHERE authorship_id IS NOT NULL AND source = 'openalex'")
    oa_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM source_authorships WHERE authorship_id IS NOT NULL AND source = 'wos'")
    wos_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM source_authorships WHERE authorship_id IS NOT NULL AND source = 'scanr'")
    scanr_total = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(DISTINCT a.id) FROM authorships a
        WHERE EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'hal')
          AND EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'openalex')
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
