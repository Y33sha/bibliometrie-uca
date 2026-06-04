"""Point d'entrée CLI : enrichissement country/ror des publishers via OpenAlex Publishers."""

import argparse
import os

from application.pipeline.publishers_journals.enrich_publishers_from_openalex import (
    run_enrich_publishers_from_openalex,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.enrich import PgEnrichQueries
from infrastructure.repositories import publisher_repository
from infrastructure.sources.api_limits import DOAJ_DELAY
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)

logger = setup_logger(
    "enrich_publishers_from_openalex", os.path.join(os.path.dirname(__file__), "logs")
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrichir les publishers via OpenAlex Publishers (country + ror)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limiter le nombre de publishers traités (0 = tous les candidats)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Aperçu sans modifier la base")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        run_enrich_publishers_from_openalex(
            conn,
            PgEnrichQueries(),
            logger,
            publisher_repo=publisher_repository(conn),
            api_key=get_openalex_api_key(conn),
            mailto=get_polite_pool_email(conn),
            openalex_publishers_api=get_api_base_urls(conn)["openalex_publishers"],
            limit=args.limit,
            dry_run=args.dry_run,
            rate_delay=DOAJ_DELAY,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
