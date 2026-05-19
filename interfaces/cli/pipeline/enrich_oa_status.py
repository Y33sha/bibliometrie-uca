"""Point d'entrée CLI : enrichissement OA via Unpaywall."""

import argparse
import asyncio
import os

import httpx

from application.pipeline.enrich.enrich_oa_status import run_enrich
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.enrich import PgEnrichQueries
from infrastructure.repositories import publication_repository
from infrastructure.sources.config import get_api_base_urls, get_openalex_email
from infrastructure.sources.unpaywall import fetch_oa_status

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
        base_url = get_api_base_urls(conn)["unpaywall"]
        email = get_openalex_email(conn)

        async def fetcher(client: httpx.AsyncClient, doi: str) -> str | None:
            return await fetch_oa_status(client, doi, base_url=base_url, email=email, logger=logger)

        asyncio.run(
            run_enrich(
                conn,
                PgEnrichQueries(),
                logger,
                pub_repo=publication_repository(conn),
                fetcher=fetcher,
                limit=args.limit,
                dry_run=args.dry_run,
            )
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
