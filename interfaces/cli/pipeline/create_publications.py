"""Point d'entrée CLI : création des publications depuis les source_publications in-perimeter."""

import argparse
import os

from application.pipeline.publications.create_publications import run
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queries.publications.create import PgPublicationsCreateQueries
from infrastructure.log import setup_logger
from infrastructure.repositories import publication_repository

logger = setup_logger("create_publications", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cree les publications pour les source_publications in-perimeter orphelins"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        run(
            conn,
            PgPublicationsCreateQueries(),
            logger,
            pub_repo=publication_repository(conn),
            dry_run=args.dry_run,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
