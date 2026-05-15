"""Point d'entrée CLI : enrichissement APC/DOAJ des revues via OpenAlex."""

import argparse
import os

from application.pipeline.enrich.enrich_journal_apc import run_enrich
from infrastructure.api_limits import DOAJ_DELAY
from infrastructure.app_config import get_api_base_urls
from infrastructure.db.engine import get_sync_engine
from infrastructure.log import setup_logger
from infrastructure.queries.enrich import PgEnrichQueries
from infrastructure.repositories import journal_repository

logger = setup_logger("enrich_journal_apc", os.path.join(os.path.dirname(__file__), "logs"))

MAILTO = "bibliometrie@uca.fr"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrichir les revues avec les APC depuis OpenAlex (prix catalogue DOAJ)"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Limiter le nombre de revues traitées (0 = toutes)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Aperçu sans modifier la base")
    parser.add_argument(
        "--reset", action="store_true", help="Réinitialiser apc_amount/is_in_doaj pour retraiter"
    )
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        run_enrich(
            conn,
            PgEnrichQueries(),
            logger,
            journal_repo=journal_repository(conn),
            mailto=MAILTO,
            openalex_sources_api=get_api_base_urls(conn)["openalex_sources"],
            limit=args.limit,
            dry_run=args.dry_run,
            reset=args.reset,
            rate_delay=DOAJ_DELAY,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
