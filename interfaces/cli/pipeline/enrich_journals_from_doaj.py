"""Point d'entrée CLI : enrichissement `doaj_payload` via l'API DOAJ."""

import argparse
import os

from application.pipeline.publishers_journals.enrich_journals_from_doaj import (
    DEFAULT_STALE_DAYS,
    DoajFetcher,
    DoajShapeMapper,
    run_enrich_journals_from_doaj,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.enrich import PgEnrichQueries
from infrastructure.repositories import journal_repository
from infrastructure.sources.api_limits import DOAJ_DELAY
from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email
from infrastructure.sources.doaj import (
    build_doaj_user_agent,
    fetch_doaj_journal,
    to_csv_shape,
)

logger = setup_logger(
    "enrich_journals_from_doaj",
    os.path.join(os.path.dirname(__file__), "logs"),
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrichit journals.doaj_payload via l'API DOAJ (ISSN)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limiter le nombre de revues traitées (0 = toutes les candidates)",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=(
            "Ne refetcher que les revues dont le dernier import DOAJ "
            f"date d'au moins N jours (défaut : {DEFAULT_STALE_DAYS})"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Aperçu sans modifier la base")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        base_url = get_api_base_urls(conn)["doaj"]
        user_agent = build_doaj_user_agent(get_polite_pool_email(conn))
        fetcher: DoajFetcher = lambda issn: fetch_doaj_journal(  # noqa: E731
            issn, base_url=base_url, user_agent=user_agent, logger=logger
        )
        mapper: DoajShapeMapper = to_csv_shape

        run_enrich_journals_from_doaj(
            conn,
            PgEnrichQueries(),
            logger,
            journal_repo=journal_repository(conn),
            fetcher=fetcher,
            mapper=mapper,
            stale_days=args.stale_days,
            limit=args.limit,
            dry_run=args.dry_run,
            rate_delay=DOAJ_DELAY,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
