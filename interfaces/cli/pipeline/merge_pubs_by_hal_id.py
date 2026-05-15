"""Point d'entrée CLI : fusion des publications par identifiant HAL (OpenAlex + ScanR)."""

import argparse
import os

from application.pipeline.publications.merge_pubs_by_hal_id import run_merge
from infrastructure.db.engine import get_sync_engine
from infrastructure.log import setup_logger
from infrastructure.queries.merge import PgMergeQueries
from infrastructure.repositories import publication_repository

logger = setup_logger("merge_pubs_by_hal_id", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fusionne les publications par identifiant HAL (OpenAlex + ScanR)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Lister sans fusionner")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        run_merge(
            conn,
            PgMergeQueries(),
            logger,
            pub_repo=publication_repository(conn),
            dry_run=args.dry_run,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
