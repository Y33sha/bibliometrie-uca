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
            SELECT DISTINCT hd.publication_id, has.person_id
            FROM hal_authorships has
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            JOIN v_active_publications vap ON vap.id = hd.publication_id
            WHERE has.person_id IS NOT NULL AND NOT has.excluded

            UNION

            SELECT DISTINCT od.publication_id, oas.person_id
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN v_active_publications vap ON vap.id = od.publication_id
            WHERE oas.person_id IS NOT NULL AND NOT oas.excluded

            UNION

            SELECT DISTINCT wd.publication_id, was.person_id
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            JOIN v_active_publications vap ON vap.id = wd.publication_id
            WHERE was.person_id IS NOT NULL AND NOT was.excluded

            UNION

            SELECT DISTINCT sd.publication_id, sas.person_id
            FROM scanr_authorships sas
            JOIN scanr_documents sd ON sd.id = sas.scanr_document_id
            JOIN v_active_publications vap ON vap.id = sd.publication_id
            WHERE sas.person_id IS NOT NULL AND NOT sas.excluded
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
              AND NOT has.excluded
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
              AND NOT oas.excluded
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
              AND NOT was.excluded
            ORDER BY wd.publication_id, was.person_id, was.id
        ) sub
        WHERE a.publication_id = sub.publication_id
          AND a.person_id = sub.person_id
          AND a.wos_authorship_id IS NULL
    """)
    wos_fk = cur.rowcount
    logger.info(f"  WoS FK : {wos_fk} liens")

    # 2d. ScanR
    cur.execute("""
        UPDATE authorships a
        SET scanr_authorship_id = sub.sas_id
        FROM (
            SELECT DISTINCT ON (sd.publication_id, sas.person_id)
                   sd.publication_id, sas.person_id, sas.id AS sas_id
            FROM scanr_authorships sas
            JOIN scanr_documents sd ON sd.id = sas.scanr_document_id
            WHERE sd.publication_id IS NOT NULL
              AND sas.person_id IS NOT NULL
              AND NOT sas.excluded
            ORDER BY sd.publication_id, sas.person_id, sas.id
        ) sub
        WHERE a.publication_id = sub.publication_id
          AND a.person_id = sub.person_id
          AND a.scanr_authorship_id IS NULL
    """)
    scanr_fk = cur.rowcount
    logger.info(f"  ScanR FK : {scanr_fk} liens")

    # ── Étape 3 : author_position et is_corresponding ──
    logger.info("Étape 3 : author_position et is_corresponding...")

    cur.execute("""
        UPDATE authorships a
        SET author_position = COALESCE(has.author_position, oas.author_position, sas.author_position, was.author_position)
        FROM authorships a2
        LEFT JOIN hal_authorships has ON has.id = a2.hal_authorship_id
        LEFT JOIN openalex_authorships oas ON oas.id = a2.openalex_authorship_id
        LEFT JOIN scanr_authorships sas ON sas.id = a2.scanr_authorship_id
        LEFT JOIN wos_authorships was ON was.id = a2.wos_authorship_id
        WHERE a.id = a2.id
          AND a.author_position IS NULL
          AND COALESCE(has.author_position, oas.author_position, sas.author_position, was.author_position) IS NOT NULL
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
    # Les 3 sources ont déjà is_uca et structure_ids peuplés par
    # populate_uca_flags.py → on fait l'union des 3 sources.
    logger.info("Étape 4 : propagation is_uca et structure_ids...")

    # Reset toutes les authorships
    cur.execute("UPDATE authorships SET is_uca = FALSE, structure_ids = NULL")
    reset_count = cur.rowcount
    logger.info(f"  Reset {reset_count} authorships")

    # Même logique pour les 3 sources : union des structure_ids, OR des is_uca
    SOURCE_QUERIES = [
        ("HAL", """
            SELECT hd.publication_id, has.person_id,
                   has.structure_ids AS struct_ids, has.is_uca AS src_is_uca
            FROM hal_authorships has
            JOIN hal_documents hd ON hd.id = has.hal_document_id
            JOIN v_active_publications vap ON vap.id = hd.publication_id
            WHERE has.structure_ids IS NOT NULL
              AND has.person_id IS NOT NULL
              AND NOT has.excluded
        """),
        ("OpenAlex", """
            SELECT od.publication_id, oas.person_id,
                   oas.structure_ids AS struct_ids, oas.is_uca AS src_is_uca
            FROM openalex_authorships oas
            JOIN openalex_documents od ON od.id = oas.openalex_document_id
            JOIN v_active_publications vap ON vap.id = od.publication_id
            WHERE oas.structure_ids IS NOT NULL
              AND oas.person_id IS NOT NULL
              AND NOT oas.excluded
        """),
        ("WoS", """
            SELECT wd.publication_id, was.person_id,
                   was.structure_ids AS struct_ids, was.is_uca AS src_is_uca
            FROM wos_authorships was
            JOIN wos_documents wd ON wd.id = was.wos_document_id
            JOIN v_active_publications vap ON vap.id = wd.publication_id
            WHERE was.structure_ids IS NOT NULL
              AND was.person_id IS NOT NULL
              AND NOT was.excluded
        """),
        ("ScanR", """
            SELECT sd.publication_id, sas.person_id,
                   sas.structure_ids AS struct_ids, sas.is_uca AS src_is_uca
            FROM scanr_authorships sas
            JOIN scanr_documents sd ON sd.id = sas.scanr_document_id
            JOIN v_active_publications vap ON vap.id = sd.publication_id
            WHERE sas.structure_ids IS NOT NULL
              AND sas.person_id IS NOT NULL
              AND NOT sas.excluded
        """),
    ]

    for source_name, source_query in SOURCE_QUERIES:
        cur.execute(f"""
            WITH src_data AS ({source_query})
            UPDATE authorships a
            SET structure_ids = (
                    SELECT array_agg(DISTINCT x)
                    FROM unnest(COALESCE(a.structure_ids, '{{}}'::int[]) || sd.struct_ids) AS x
                ),
                is_uca = a.is_uca OR sd.src_is_uca,
                updated_at = now()
            FROM src_data sd
            WHERE a.publication_id = sd.publication_id
              AND a.person_id = sd.person_id
        """)
        logger.info(f"  {source_name} : {cur.rowcount} authorships mises à jour")

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
