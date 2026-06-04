"""Point d'entrée CLI : fallback `publishers.country` via Crossref Members."""

import argparse
import os

from application.pipeline.publishers_journals.enrich_publishers_from_crossref_members import (
    CrossrefMemberFetcher,
    run_enrich_publishers_from_crossref_members,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.enrich import PgEnrichQueries
from infrastructure.repositories import publisher_repository
from infrastructure.sources.api_limits import CROSSREF_DELAY
from infrastructure.sources.config import get_polite_pool_email
from infrastructure.sources.crossref.members import fetch_crossref_member
from infrastructure.sources.doi_prefixes.clients import build_user_agent

logger = setup_logger(
    "enrich_publishers_from_crossref_members",
    os.path.join(os.path.dirname(__file__), "logs"),
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fallback publishers.country via api.crossref.org/members"
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
        user_agent = build_user_agent(get_polite_pool_email(conn))
        fetcher: CrossrefMemberFetcher = lambda member_id: fetch_crossref_member(  # noqa: E731
            member_id, user_agent=user_agent, logger=logger
        )

        run_enrich_publishers_from_crossref_members(
            conn,
            PgEnrichQueries(),
            logger,
            publisher_repo=publisher_repository(conn),
            fetcher=fetcher,
            limit=args.limit,
            dry_run=args.dry_run,
            rate_delay=CROSSREF_DELAY,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
