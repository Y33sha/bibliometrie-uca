"""Point d'entrée CLI : rattache ou crée les publications canoniques pour les source_publications orphelins (tous périmètres, création gated par périmètre), et rafraîchit les pubs stale."""

import argparse
import os

from application.pipeline.publications.create_publications import run
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.publications_create import (
    PgPublicationsCreateQueries,
)
from infrastructure.repositories import audit_repository, publication_repository

logger = setup_logger(
    "create_publications", os.path.join(os.path.dirname(__file__), "logs")
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rattache ou crée les publications canoniques pour les source_publications orphelins (création gated par périmètre, rattachement universel), puis rafraîchit les publications stale"
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
            audit_repo=audit_repository(conn),
            dry_run=args.dry_run,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
