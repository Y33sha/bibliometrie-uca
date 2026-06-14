"""Point d'entrée CLI : typage publisher_type des publishers via ROR."""

import argparse
import os

from application.pipeline.publishers_journals.enrich_publishers_from_ror import (
    RorFetcher,
    run_enrich_publishers_from_ror,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.enrich import PgEnrichQueries
from infrastructure.repositories import publisher_repository
from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email
from infrastructure.sources.ror import build_ror_user_agent, fetch_ror_record

logger = setup_logger("enrich_publishers_from_ror", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Typer publishers (publisher_type) via leur record ROR"
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
        base_url = get_api_base_urls(conn)["ror"]
        user_agent = build_ror_user_agent(get_polite_pool_email(conn))
        fetcher: RorFetcher = lambda ror: fetch_ror_record(  # noqa: E731
            ror, base_url=base_url, user_agent=user_agent, logger=logger
        )

        run_enrich_publishers_from_ror(
            conn,
            PgEnrichQueries(),
            logger,
            publisher_repo=publisher_repository(conn),
            fetcher=fetcher,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
