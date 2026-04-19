"""Point d'entrée CLI : fusion des publications par NNT."""

import argparse
import os

from application.pipeline.merge.merge_pubs_by_nnt import run_merge
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.merge import PgMergeQueries
from infrastructure.log import setup_logger

logger = setup_logger("merge_pubs_by_nnt", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fusionne les publications par NNT (cross-source)")
    parser.add_argument("--dry-run", action="store_true", help="Lister sans fusionner")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        run_merge(cur, conn, PgMergeQueries(), logger, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
