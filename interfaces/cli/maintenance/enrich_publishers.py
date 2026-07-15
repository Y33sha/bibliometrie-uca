"""Enrichissement (cosmétique) du `country` des éditeurs depuis OpenAlex Publishers.

Hors pipeline (champs d'affichage), lancé à la demande. Politique « NULL only » : les valeurs saisies par un administrateur sont préservées ; idempotent.

Usage :
    python -m interfaces.cli.maintenance.enrich_publishers [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from application.services.publishers.enrich_country import run_enrich_publishers_from_openalex
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import publisher_repository
from infrastructure.sources.api_limits import DOAJ_DELAY
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)

log = setup_logger("enrich_publishers", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limiter le nombre d'éditeurs traités (0 = tous les candidats).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Aperçu sans modifier la base.")
    args = parser.parse_args()

    api_base_urls = get_api_base_urls()
    conn = get_sync_engine().connect()
    try:
        repo = publisher_repository(conn)
        run_enrich_publishers_from_openalex(
            conn,
            log,
            publisher_repo=repo,
            api_key=get_openalex_api_key(conn),
            mailto=get_polite_pool_email(conn),
            openalex_publishers_api=api_base_urls["openalex_publishers"],
            limit=args.limit,
            dry_run=args.dry_run,
            rate_delay=DOAJ_DELAY,
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
