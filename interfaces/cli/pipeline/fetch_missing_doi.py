"""Point d'entrée CLI : fetch des DOI manquants dans une source cible.

Composition root : sélectionne l'adapter async selon `--target`, ouvre
la connexion, appelle `application.pipeline.fetch_missing_doi.run_async`.

Les 4 sources (hal, openalex, wos, scanr) utilisent le chemin async
(`AsyncFetchMissingDoiAdapter` + `httpx.AsyncClient`), avec un débit
mesuré ~18 req/s sur OpenAlex (le polite pool autorise 10 req/s par
client + bursts).

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
from typing import cast

from application.pipeline.fetch_missing_doi import AsyncFetchMissingDoiAdapter, run_async
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.common import get_cross_import_dois
from infrastructure.sources.crossref.fetch_missing_doi import CrossrefFetchMissingDoiAdapter
from infrastructure.sources.hal.fetch_missing_doi import HalFetchMissingDoiAdapter
from infrastructure.sources.openalex.fetch_missing_doi import OpenalexFetchMissingDoiAdapter
from infrastructure.sources.scanr.fetch_missing_doi import ScanrFetchMissingDoiAdapter
from infrastructure.sources.wos.fetch_missing_doi import WosFetchMissingDoiAdapter

logger = setup_logger("fetch_missing_doi", os.path.join(os.path.dirname(__file__), "logs"))


# Cast nécessaire : mypy ne reconnaît pas la conformité structurelle d'une
# classe concrète à un Protocol pour `type[Protocol]` (il exigerait un
# héritage explicite, qui violerait le contrat DDD application↔infrastructure).
# Le duck typing du Protocol fonctionne normalement à l'usage des instances.
ADAPTERS: dict[str, type[AsyncFetchMissingDoiAdapter]] = cast(
    "dict[str, type[AsyncFetchMissingDoiAdapter]]",
    {
        "hal": HalFetchMissingDoiAdapter,
        "openalex": OpenalexFetchMissingDoiAdapter,
        "wos": WosFetchMissingDoiAdapter,
        "scanr": ScanrFetchMissingDoiAdapter,
        "crossref": CrossrefFetchMissingDoiAdapter,
    },
)


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
    conn = get_sync_engine().connect()
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
        conn.close()


if __name__ == "__main__":
    main()
