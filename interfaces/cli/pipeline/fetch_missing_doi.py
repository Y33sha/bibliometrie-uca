"""Point d'entrée CLI : fetch des DOI manquants dans une source cible.

Composition root : sélectionne l'adapter async selon `--target`, ouvre
la connexion, appelle `application.pipeline.fetch_missing_doi.run_async`.

§2.14 : les 4 sources (hal, openalex, wos, scanr) utilisent le chemin
async (`AsyncFetchMissingDoiAdapter` + `httpx.AsyncClient`). Gain mesuré
sur OpenAlex : ~×3.6 vs sync (18 req/s vs ~5 req/s plafond sync).

Usage :
    python -m interfaces.cli.pipeline.fetch_missing_doi --target hal
    python -m interfaces.cli.pipeline.fetch_missing_doi --target openalex --all
    python -m interfaces.cli.pipeline.fetch_missing_doi --target wos --dry-run
    python -m interfaces.cli.pipeline.fetch_missing_doi --target scanr --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import os

from application.pipeline.fetch_missing_doi import AsyncFetchMissingDoiAdapter, run_async
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger
from infrastructure.sources.common import get_cross_import_dois
from infrastructure.sources.crossref.fetch_missing_doi import CrossrefFetchMissingDoiAdapter
from infrastructure.sources.hal.fetch_missing_doi import HalFetchMissingDoiAdapter
from infrastructure.sources.openalex.fetch_missing_doi import OpenalexFetchMissingDoiAdapter
from infrastructure.sources.scanr.fetch_missing_doi import ScanrFetchMissingDoiAdapter
from infrastructure.sources.wos.fetch_missing_doi import WosFetchMissingDoiAdapter

logger = setup_logger("fetch_missing_doi", os.path.join(os.path.dirname(__file__), "logs"))


ADAPTERS: dict[str, type[AsyncFetchMissingDoiAdapter]] = {
    "hal": HalFetchMissingDoiAdapter,
    "openalex": OpenalexFetchMissingDoiAdapter,
    "wos": WosFetchMissingDoiAdapter,
    "scanr": ScanrFetchMissingDoiAdapter,
    "crossref": CrossrefFetchMissingDoiAdapter,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch des DOI manquants dans une source cible")
    parser.add_argument("--target", choices=sorted(ADAPTERS.keys()), required=True)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Considérer tout le staging (sinon, uniquement processed=FALSE)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compter sans fetch/insert")
    parser.add_argument("--limit", type=int, help="Nombre max de DOI à traiter")
    args = parser.parse_args()

    adapter = ADAPTERS[args.target]()
    conn = get_connection()
    try:
        asyncio.run(
            run_async(
                conn,
                adapter,
                logger,
                cross_import_dois_reader=get_cross_import_dois,
                all_staged=args.all,
                dry_run=args.dry_run,
                limit=args.limit,
            )
        )
    finally:
        if not conn.closed:
            conn.close()


if __name__ == "__main__":
    main()
