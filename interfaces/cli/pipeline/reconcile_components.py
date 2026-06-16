"""Point d'entrée CLI : réconciliation des composantes (fusion des publications en surplus)."""

import argparse
import os

from application.pipeline.publications.reconcile_components import run
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.publications_reconciliation import (
    PgPublicationsReconciliationQueries,
)
from infrastructure.repositories import audit_repository, publication_repository

logger = setup_logger("reconcile_components", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Réconcilie les composantes (fusion en surplus)")
    parser.add_argument("--dry-run", action="store_true", help="Planifier sans appliquer")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            pub_repo=publication_repository(conn),
            audit_repo=audit_repository(conn),
            dry_run=args.dry_run,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
