"""
Fusionne les publications qui partagent le même NNT dans external_ids.

Quand plusieurs source_publications (theses.fr, OpenAlex, ScanR) pointent vers
des publications différentes mais ont le même NNT, on fusionne ces publications
en une seule.

Le SQL est isolé dans `infrastructure/db/queries/merge.py`.

Usage:
    python merge_pubs_by_nnt.py              # fusionner
    python merge_pubs_by_nnt.py --dry-run    # lister sans fusionner
"""

import argparse
import os
from typing import Any

from application.publications import merge_publications as _merge_pub
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.merge import (
    find_nnt_duplicates,
    rank_publications_by_merge_priority,
)
from infrastructure.log import setup_logger

log = setup_logger("merge_pubs_by_nnt", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> Any:
    parser = argparse.ArgumentParser(description="Fusionne les publications par NNT (cross-source)")
    parser.add_argument("--dry-run", action="store_true", help="Lister sans fusionner")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        duplicates = find_nnt_duplicates(cur)
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

            ranked = rank_publications_by_merge_priority(cur, pub_ids)
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
