"""Point d'entrée CLI : typage `journal_type` (+ APC opportuniste) des revues via OpenAlex Sources."""

import argparse
import os

from application.pipeline.publishers_journals.enrich_journals_from_openalex import (
    run_enrich_journals_from_openalex,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.enrich import PgEnrichQueries
from infrastructure.repositories import journal_repository
from infrastructure.sources.api_limits import DOAJ_DELAY
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)

logger = setup_logger(
    "enrich_journals_from_openalex", os.path.join(os.path.dirname(__file__), "logs")
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Typer les revues via OpenAlex Sources (journal_type + APC opportuniste)"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Limiter le nombre de revues traitées (0 = toutes)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Aperçu sans modifier la base")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        run_enrich_journals_from_openalex(
            conn,
            PgEnrichQueries(),
            logger,
            journal_repo=journal_repository(conn),
            api_key=get_openalex_api_key(conn),
            mailto=get_polite_pool_email(conn),
            openalex_sources_api=get_api_base_urls()["openalex_sources"],
            limit=args.limit,
            dry_run=args.dry_run,
            rate_delay=DOAJ_DELAY,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
