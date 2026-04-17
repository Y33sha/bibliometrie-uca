"""
Script one-shot : fusionne les publications doublonnées par DOI versionné (.v1, .v2…).

Pour chaque paire (DOI concept, DOI concept.vN), garde la publication
avec le DOI concept et fusionne l'autre dedans.

Usage:
    python scripts/merge_versioned_doi_duplicates.py              # exécuter
    python scripts/merge_versioned_doi_duplicates.py --dry-run    # lister sans modifier
"""

import argparse
import os

from psycopg2.extras import RealDictCursor

from db.connection import get_connection
from services.publications import merge_publications
from utils.log import setup_logger

log = setup_logger("merge_versioned_doi", os.path.join(os.path.dirname(__file__), "..", "processing", "logs"))


def find_versioned_duplicates(cur):
    cur.execute("""
        SELECT p1.id AS target_id, p1.doi AS target_doi,
               p2.id AS source_id, p2.doi AS source_doi
        FROM publications p1
        JOIN publications p2
          ON p2.doi LIKE p1.doi || '.v%'
         AND substring(p2.doi FROM length(p1.doi) + 2) ~ '^v\\d+$'
        WHERE p1.doi !~ '\\.v\\d+$'
    """)
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description="Fusionne les doublons DOI versionnés")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        pairs = find_versioned_duplicates(cur)
        log.info(f"{len(pairs)} paire(s) trouvée(s)")

        merged = 0
        for p in pairs:
            log.info(f"  {'[DRY] ' if args.dry_run else ''}"
                     f"pub {p['source_id']} ({p['source_doi']}) → "
                     f"pub {p['target_id']} ({p['target_doi']})")
            if not args.dry_run:
                try:
                    cur.execute("SAVEPOINT merge_vdoi")
                    merge_publications(cur, p['target_id'], p['source_id'])
                    cur.execute("RELEASE SAVEPOINT merge_vdoi")
                    merged += 1
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT merge_vdoi")
                    log.warning(f"  Échec fusion {p['source_doi']}: {e}")

        if not args.dry_run:
            conn.commit()
            log.info(f"{merged}/{len(pairs)} publications fusionnées. Commit OK.")
        else:
            log.info(f"[DRY RUN] {len(pairs)} fusions à faire.")

    except Exception as e:
        conn.rollback()
        log.error(f"Erreur : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
