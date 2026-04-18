"""
Fusionne les publications qui partagent le même NNT dans external_ids.

Quand plusieurs source_publications (theses.fr, OpenAlex, ScanR) pointent vers
des publications différentes mais ont le même NNT, on fusionne ces publications
en une seule.

Usage:
    python merge_pubs_by_nnt.py              # fusionner
    python merge_pubs_by_nnt.py --dry-run    # lister sans fusionner
"""

import argparse
import os

from psycopg2.extras import RealDictCursor

from db.connection import get_connection
from application.publications import merge_publications as _merge_pub
from utils.log import setup_logger

log = setup_logger("merge_pubs_by_nnt", os.path.join(os.path.dirname(__file__), "logs"))


def find_duplicates(cur):
    """Trouve les NNT qui pointent vers des publications différentes."""
    cur.execute("""
        SELECT sd.external_ids->>'nnt' AS nnt,
               array_agg(DISTINCT sd.publication_id ORDER BY sd.publication_id) AS pub_ids,
               array_agg(DISTINCT sd.source::text ORDER BY sd.source::text) AS sources
        FROM source_publications sd
        WHERE sd.external_ids->>'nnt' IS NOT NULL
          AND sd.publication_id IS NOT NULL
        GROUP BY sd.external_ids->>'nnt'
        HAVING COUNT(DISTINCT sd.publication_id) > 1
        ORDER BY sd.external_ids->>'nnt'
    """)
    return cur.fetchall()


def choose_target(cur, pub_ids):
    """Choisit la publication à garder.

    Priorité : celle avec DOI > celle avec le plus de source_publications > id le plus bas.
    """
    cur.execute(
        """
        SELECT p.id, p.doi,
               (SELECT COUNT(*) FROM source_publications sd WHERE sd.publication_id = p.id) AS sd_count
        FROM publications p
        WHERE p.id = ANY(%s)
        ORDER BY
            (p.doi IS NOT NULL AND p.doi ~ '^10\\.') DESC,
            (SELECT COUNT(*) FROM source_publications sd WHERE sd.publication_id = p.id) DESC,
            p.id ASC
    """,
        (pub_ids,),
    )
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description="Fusionne les publications par NNT (cross-source)")
    parser.add_argument("--dry-run", action="store_true", help="Lister sans fusionner")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        duplicates = find_duplicates(cur)
        log.info(f"NNT avec publications multiples : {len(duplicates)}")

        if not duplicates:
            log.info("Rien à faire.")
            return

        merged = 0
        errors = 0

        for dup in duplicates:
            nnt = dup["nnt"]
            pub_ids = dup["pub_ids"]
            sources = dup["sources"]

            ranked = choose_target(cur, pub_ids)
            target = ranked[0]
            to_merge = ranked[1:]

            for source in to_merge:
                label = (
                    f"NNT={nnt} : pub {source['id']} → {target['id']}"
                    f" (sources: {', '.join(sources)})"
                )

                if args.dry_run:
                    log.info(f"  [DRY] {label}")
                    merged += 1
                    continue

                try:
                    cur.execute("SAVEPOINT merge_nnt")
                    _merge_pub(cur, target["id"], source["id"])
                    cur.execute("RELEASE SAVEPOINT merge_nnt")
                    log.info(f"  [MERGE] {label}")
                    merged += 1
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT merge_nnt")
                    log.warning(f"  Échec {label}: {e}")
                    errors += 1

        if not args.dry_run:
            conn.commit()
            log.info("Commit OK.")

        log.info("\n=== Résumé ===")
        log.info(f"  Fusions {'(dry-run)' if args.dry_run else 'appliquées'} : {merged}")
        log.info(f"  Erreurs : {errors}")
        if args.dry_run and merged:
            log.info("[DRY RUN] Aucune modification.")

    except Exception as e:
        conn.rollback()
        log.error(f"Erreur : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
