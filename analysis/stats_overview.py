"""
Statistiques exploratoires sur la base publisher-stats.

Usage:
    python stats_overview.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def query(cur, sql: str, headers: list = None):
    """Exécute une requête et affiche les résultats en tableau."""
    cur.execute(sql)
    rows = cur.fetchall()
    if not rows:
        print("  (aucun résultat)")
        return rows

    if headers:
        col_widths = [max(len(str(h)), max(len(str(r[i])) for r in rows))
                      for i, h in enumerate(headers)]
        header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        print(f"  {header_line}")
        print(f"  {'-+-'.join('-'*w for w in col_widths)}")
        for row in rows:
            line = " | ".join(str(v).ljust(w) for v, w in zip(row, col_widths))
            print(f"  {line}")
    else:
        for row in rows:
            print(f"  {row}")

    return rows


def main():
    conn = get_connection()
    cur = conn.cursor()

    # ===== VUE D'ENSEMBLE =====
    section("VUE D'ENSEMBLE")
    query(cur, """
        SELECT 'publications' AS table_name, COUNT(*) FROM publications
        UNION ALL SELECT 'authors', COUNT(*) FROM authors
        UNION ALL SELECT 'journals', COUNT(*) FROM journals
        UNION ALL SELECT 'publishers', COUNT(*) FROM publishers
        UNION ALL SELECT 'publication_authors', COUNT(*) FROM publication_authors
        UNION ALL SELECT 'publication_sources', COUNT(*) FROM publication_sources
        UNION ALL SELECT 'staging_openalex', COUNT(*) FROM staging_openalex
        UNION ALL SELECT 'staging_hal', COUNT(*) FROM staging_hal
    """, ["table", "count"])

    # ===== PUBLICATIONS PAR ANNÉE =====
    section("PUBLICATIONS PAR ANNÉE")
    query(cur, """
        SELECT pub_year, COUNT(*) AS total
        FROM publications
        GROUP BY pub_year
        ORDER BY pub_year
    """, ["année", "total"])

    # ===== PUBLICATIONS PAR TYPE DE DOCUMENT =====
    section("PUBLICATIONS PAR TYPE DE DOCUMENT")
    query(cur, """
        SELECT doc_type, COUNT(*) AS total
        FROM publications
        GROUP BY doc_type
        ORDER BY total DESC
    """, ["type", "total"])

    # ===== COUVERTURE PAR SOURCE =====
    section("COUVERTURE PAR SOURCE")
    query(cur, """
        SELECT source, COUNT(*) AS nb_links
        FROM publication_sources
        GROUP BY source
    """, ["source", "nb liens"])

    query(cur, """
        SELECT
            CASE
                WHEN COUNT(DISTINCT ps.source) = 2 THEN 'HAL + OpenAlex'
                WHEN MIN(ps.source::text) = 'hal' THEN 'HAL uniquement'
                ELSE 'OpenAlex uniquement'
            END AS couverture,
            COUNT(*) AS nb_publications
        FROM publications p
        JOIN publication_sources ps ON ps.publication_id = p.id
        GROUP BY p.id
        ORDER BY couverture
    """, ["couverture", "nb publications"])

    # ===== STATUT OPEN ACCESS =====
    section("STATUT OPEN ACCESS")
    query(cur, """
        SELECT oa_status, COUNT(*) AS total
        FROM publications
        GROUP BY oa_status
        ORDER BY total DESC
    """, ["statut OA", "total"])

    # ===== TOP 20 ÉDITEURS =====
    section("TOP 20 ÉDITEURS (par nombre de publications)")
    query(cur, """
        SELECT pub.name, COUNT(DISTINCT p.id) AS nb_publis
        FROM publications p
        JOIN journals j ON j.id = p.journal_id
        JOIN publishers pub ON pub.id = j.publisher_id
        GROUP BY pub.id, pub.name
        ORDER BY nb_publis DESC
        LIMIT 20
    """, ["éditeur", "nb publis"])

    # ===== TOP 20 REVUES =====
    section("TOP 20 REVUES (par nombre de publications)")
    query(cur, """
        SELECT j.title, pub.name AS editeur, COUNT(DISTINCT p.id) AS nb_publis
        FROM publications p
        JOIN journals j ON j.id = p.journal_id
        LEFT JOIN publishers pub ON pub.id = j.publisher_id
        GROUP BY j.id, j.title, pub.name
        ORDER BY nb_publis DESC
        LIMIT 20
    """, ["revue", "éditeur", "nb publis"])

    # ===== RATTACHEMENT LABO (via HAL) =====
    section("RATTACHEMENT LABO (publis HAL avec collection)")
    query(cur, """
        SELECT l.code, l.name,
               COUNT(DISTINCT pa.publication_id) AS nb_publis
        FROM publication_authors pa
        JOIN laboratories l ON l.id = pa.laboratory_id
        GROUP BY l.code, l.name
        ORDER BY nb_publis DESC
    """, ["code labo", "nom labo", "nb publis"])

    # ===== PUBLICATIONS SANS REVUE =====
    section("PUBLICATIONS SANS REVUE NI ÉDITEUR")
    query(cur, """
        SELECT doc_type, COUNT(*) AS total
        FROM publications
        WHERE journal_id IS NULL
        GROUP BY doc_type
        ORDER BY total DESC
    """, ["type", "sans revue"])

    total_pubs = cur.execute("SELECT COUNT(*) FROM publications")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM publications WHERE journal_id IS NULL")
    sans_revue = cur.fetchone()[0]
    print(f"\n  Total sans revue : {sans_revue}/{total} ({100*sans_revue/total:.1f}%)")

    # ===== LANGUES =====
    section("LANGUES")
    query(cur, """
        SELECT COALESCE(language, '(non renseigné)') AS langue,
               COUNT(*) AS total
        FROM publications
        GROUP BY language
        ORDER BY total DESC
        LIMIT 10
    """, ["langue", "total"])

    # ===== QUALITÉ DOI =====
    section("COUVERTURE DOI")
    cur.execute("SELECT COUNT(*) FROM publications WHERE doi IS NOT NULL")
    with_doi = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM publications WHERE doi IS NULL")
    without_doi = cur.fetchone()[0]
    print(f"  Avec DOI    : {with_doi} ({100*with_doi/total:.1f}%)")
    print(f"  Sans DOI    : {without_doi} ({100*without_doi/total:.1f}%)")

    # ===== APERÇU FAUX POSITIFS POTENTIELS =====
    section("APERÇU : PUBLIS OPENALEX SANS MATCH HAL (potentiels faux positifs)")
    query(cur, """
        SELECT p.pub_year, COUNT(*) AS nb
        FROM publications p
        JOIN publication_sources ps ON ps.publication_id = p.id
        WHERE ps.source = 'openalex'
          AND NOT EXISTS (
              SELECT 1 FROM publication_sources ps2
              WHERE ps2.publication_id = p.id AND ps2.source = 'hal'
          )
        GROUP BY p.pub_year
        ORDER BY p.pub_year
    """, ["année", "nb OpenAlex-only"])

    print("\n  (Note: pas tous des faux positifs — beaucoup sont simplement")
    print("   absents de HAL. Le tri par affiliations sera nécessaire.)")

    conn.close()
    print(f"\n{'='*60}")
    print("  Fin des statistiques")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
