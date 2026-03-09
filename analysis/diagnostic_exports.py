"""
Exports de diagnostic pour la vérification des données.

Usage:
    python diagnostic_exports.py                # tous les exports
    python diagnostic_exports.py --false-pos    # faux positifs uniquement
    python diagnostic_exports.py --lab-compare  # comparaison labos uniquement

Génère des CSV dans data/ :
    - false_positives.csv : publis OpenAlex-only non validées UCA
    - lab_comparison.csv  : stats par labo HAL vs OpenAlex
"""

import argparse
import csv
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def export_csv(cur, query: str, filename: str, headers: list):
    """Exécute une requête et exporte en CSV."""
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, filename)

    cur.execute(query)
    rows = cur.fetchall()

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    logger.info(f"  {filename} : {len(rows)} lignes → {filepath}")
    return rows


def export_false_positives(cur):
    """
    Exporte les publications OpenAlex-only non validées UCA.
    Ce sont les probables faux positifs du filtre lineage.
    """
    logger.info("\n=== FAUX POSITIFS PROBABLES ===")

    # Vue d'ensemble
    cur.execute("""
        SELECT COUNT(*) FROM publications WHERE is_validated = FALSE
    """)
    total_non_valid = cur.fetchone()[0]
    logger.info(f"Publications non validées : {total_non_valid}")

    # Parmi celles-ci, combien sont OpenAlex-only ?
    cur.execute("""
        SELECT COUNT(*)
        FROM publications p
        WHERE p.is_validated = FALSE
          AND EXISTS (
              SELECT 1 FROM publication_sources ps
              WHERE ps.publication_id = p.id AND ps.source = 'openalex'
          )
          AND NOT EXISTS (
              SELECT 1 FROM publication_sources ps
              WHERE ps.publication_id = p.id AND ps.source = 'hal'
          )
    """)
    oa_only_non_valid = cur.fetchone()[0]
    logger.info(f"  dont OpenAlex-only : {oa_only_non_valid}")

    # Export détaillé
    export_csv(cur, """
        SELECT
            p.id,
            p.title,
            p.pub_year,
            p.doi,
            p.doc_type::text,
            j.title AS journal,
            pub.name AS publisher,
            -- Institutions OpenAlex attribuées (depuis raw_json)
            (
                SELECT string_agg(DISTINCT inst, ' | ')
                FROM (
                    SELECT DISTINCT pa.raw_affiliation AS inst
                    FROM publication_authors pa
                    WHERE pa.publication_id = p.id
                      AND pa.source = 'openalex'
                      AND pa.raw_affiliation IS NOT NULL
                    LIMIT 5
                ) sub
            ) AS sample_affiliations,
            ps.source_id AS openalex_id
        FROM publications p
        JOIN publication_sources ps ON ps.publication_id = p.id AND ps.source = 'openalex'
        LEFT JOIN journals j ON j.id = p.journal_id
        LEFT JOIN publishers pub ON pub.id = j.publisher_id
        WHERE p.is_validated = FALSE
          AND NOT EXISTS (
              SELECT 1 FROM publication_sources ps2
              WHERE ps2.publication_id = p.id AND ps2.source = 'hal'
          )
        ORDER BY p.pub_year DESC, p.title
    """, "false_positives.csv", [
        "id", "title", "year", "doi", "doc_type",
        "journal", "publisher", "sample_affiliations", "openalex_id"
    ])

    # Résumé par année
    cur.execute("""
        SELECT p.pub_year, COUNT(*) AS nb
        FROM publications p
        WHERE p.is_validated = FALSE
          AND EXISTS (
              SELECT 1 FROM publication_sources ps
              WHERE ps.publication_id = p.id AND ps.source = 'openalex'
          )
          AND NOT EXISTS (
              SELECT 1 FROM publication_sources ps
              WHERE ps.publication_id = p.id AND ps.source = 'hal'
          )
        GROUP BY p.pub_year
        ORDER BY p.pub_year
    """)
    logger.info("\n  Faux positifs probables par année :")
    for row in cur.fetchall():
        logger.info(f"    {row[0]} : {row[1]}")

    # Résumé par type de doc
    cur.execute("""
        SELECT p.doc_type::text, COUNT(*) AS nb
        FROM publications p
        WHERE p.is_validated = FALSE
          AND EXISTS (
              SELECT 1 FROM publication_sources ps
              WHERE ps.publication_id = p.id AND ps.source = 'openalex'
          )
          AND NOT EXISTS (
              SELECT 1 FROM publication_sources ps
              WHERE ps.publication_id = p.id AND ps.source = 'hal'
          )
        GROUP BY p.doc_type
        ORDER BY nb DESC
    """)
    logger.info("\n  Faux positifs probables par type de doc :")
    for row in cur.fetchall():
        logger.info(f"    {row[0]:20s} : {row[1]}")


def export_lab_comparison(cur):
    """
    Compare les stats par labo entre HAL et OpenAlex.
    Permet de repérer les labos sur/sous-représentés dans une source.
    """
    logger.info("\n=== COMPARAISON HAL vs OPENALEX PAR LABO ===")

    export_csv(cur, """
        WITH hal_stats AS (
            SELECT
                pa.laboratory_id AS lab_id,
                COUNT(DISTINCT pa.publication_id) AS nb_hal
            FROM publication_authors pa
            WHERE pa.source = 'hal'
              AND pa.laboratory_id IS NOT NULL
            GROUP BY pa.laboratory_id
        ),
        oa_stats AS (
            SELECT
                pa.laboratory_id AS lab_id,
                COUNT(DISTINCT pa.publication_id) AS nb_oa
            FROM publication_authors pa
            WHERE pa.source = 'openalex'
              AND pa.laboratory_id IS NOT NULL
              AND pa.is_uca_author = TRUE
            GROUP BY pa.laboratory_id
        ),
        combined_stats AS (
            SELECT
                pa.laboratory_id AS lab_id,
                COUNT(DISTINCT pa.publication_id) AS nb_combined
            FROM publication_authors pa
            WHERE pa.laboratory_id IS NOT NULL
              AND pa.is_uca_author = TRUE
            GROUP BY pa.laboratory_id
        )
        SELECT
            l.code AS lab_code,
            l.name AS lab_name,
            COALESCE(h.nb_hal, 0) AS publis_hal,
            COALESCE(o.nb_oa, 0) AS publis_openalex,
            COALESCE(c.nb_combined, 0) AS publis_combined,
            -- Publis dans les deux sources
            GREATEST(0,
                COALESCE(h.nb_hal, 0) + COALESCE(o.nb_oa, 0) - COALESCE(c.nb_combined, 0)
            ) AS overlap,
            -- Publis HAL-only
            GREATEST(0,
                COALESCE(c.nb_combined, 0) - COALESCE(o.nb_oa, 0)
            ) AS hal_only,
            -- Publis OpenAlex-only
            GREATEST(0,
                COALESCE(c.nb_combined, 0) - COALESCE(h.nb_hal, 0)
            ) AS openalex_only
        FROM laboratories l
        LEFT JOIN hal_stats h ON h.lab_id = l.id
        LEFT JOIN oa_stats o ON o.lab_id = l.id
        LEFT JOIN combined_stats c ON c.lab_id = l.id
        ORDER BY COALESCE(c.nb_combined, 0) DESC
    """, "lab_comparison.csv", [
        "lab_code", "lab_name", "publis_hal", "publis_openalex",
        "publis_combined", "overlap", "hal_only", "openalex_only"
    ])

    # Affichage résumé
    cur.execute("""
        WITH hal_stats AS (
            SELECT pa.laboratory_id AS lab_id, COUNT(DISTINCT pa.publication_id) AS nb
            FROM publication_authors pa
            WHERE pa.source = 'hal' AND pa.laboratory_id IS NOT NULL
            GROUP BY pa.laboratory_id
        ),
        oa_stats AS (
            SELECT pa.laboratory_id AS lab_id, COUNT(DISTINCT pa.publication_id) AS nb
            FROM publication_authors pa
            WHERE pa.source = 'openalex' AND pa.laboratory_id IS NOT NULL AND pa.is_uca_author = TRUE
            GROUP BY pa.laboratory_id
        )
        SELECT
            l.code,
            l.name,
            COALESCE(h.nb, 0) AS hal,
            COALESCE(o.nb, 0) AS oa
        FROM laboratories l
        LEFT JOIN hal_stats h ON h.lab_id = l.id
        LEFT JOIN oa_stats o ON o.lab_id = l.id
        ORDER BY COALESCE(h.nb, 0) + COALESCE(o.nb, 0) DESC
    """)
    rows = cur.fetchall()

    logger.info(f"\n  {'Code':<20s} {'Nom':<20s} {'HAL':>6s} {'OA':>6s} {'Ratio':>8s}")
    logger.info(f"  {'-'*20} {'-'*20} {'-'*6} {'-'*6} {'-'*8}")
    for row in rows:
        code, name, hal, oa = row
        ratio = f"{oa/hal:.2f}" if hal > 0 else "∞" if oa > 0 else "-"
        logger.info(f"  {code:<20s} {name:<20s} {hal:>6d} {oa:>6d} {ratio:>8s}")


def main():
    parser = argparse.ArgumentParser(description="Exports de diagnostic")
    parser.add_argument("--false-pos", action="store_true", help="Faux positifs uniquement")
    parser.add_argument("--lab-compare", action="store_true", help="Comparaison labos uniquement")
    args = parser.parse_args()

    do_all = not args.false_pos and not args.lab_compare

    conn = get_connection()
    cur = conn.cursor()

    if do_all or args.false_pos:
        export_false_positives(cur)

    if do_all or args.lab_compare:
        export_lab_comparison(cur)

    conn.close()
    logger.info(f"\nFichiers exportés dans : {DATA_DIR}")


if __name__ == "__main__":
    main()
