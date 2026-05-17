"""Point d'entrée CLI : enrichissement OA via Unpaywall."""

import argparse
import os

from application.pipeline.enrich.enrich_oa_status import run_enrich
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.enrich import PgEnrichQueries
from infrastructure.repositories import publication_repository
from infrastructure.sources.api_limits import UNPAYWALL_DELAY
from infrastructure.sources.config import get_api_base_urls

logger = setup_logger("enrich_oa_unpaywall", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=0, help="Nombre max de publis à traiter (0=toutes)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Afficher sans modifier la base")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        run_enrich(
            conn,
            PgEnrichQueries(),
            logger,
            pub_repo=publication_repository(conn),
            unpaywall_base=get_api_base_urls(conn)["unpaywall"],
            limit=args.limit,
            dry_run=args.dry_run,
            rate_delay=UNPAYWALL_DELAY,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
