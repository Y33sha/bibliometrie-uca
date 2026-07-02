"""Point d'entrée CLI : fetch des entrées HAL manquantes via OA / ScanR / NNT."""

from __future__ import annotations

import argparse
import asyncio
import os

from application.pipeline.extract.fetch_missing_hal import (
    fetch_missing_hal_by_id,
    fetch_missing_hal_by_nnt,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.hal.fetch_missing_hal import PgHalFetchMissingAdapter

logger = setup_logger("fetch_missing_hal", os.path.join(os.path.dirname(__file__), "logs"))


async def _main_async() -> None:
    parser = argparse.ArgumentParser(
        description="Récupère les entrées HAL manquantes découvertes via OpenAlex / ScanR / NNT"
    )
    parser.add_argument("--dry-run", action="store_true", help="Lister sans télécharger")
    parser.add_argument("--stats", action="store_true", help="Statistiques uniquement")
    parser.add_argument(
        "--mode",
        choices=["full", "weekly", "daily"],
        default="full",
        help="Mode pipeline (NNT ignoré en daily/weekly)",
    )
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    adapter = PgHalFetchMissingAdapter()
    try:
        await fetch_missing_hal_by_id(
            conn, adapter, logger, dry_run=args.dry_run, stats_only=args.stats
        )
        # NNT trop volumineux pour un run incrémental : réservé au mode full.
        if args.mode == "full":
            await fetch_missing_hal_by_nnt(
                conn, adapter, logger, dry_run=args.dry_run, stats_only=args.stats
            )
        else:
            logger.info("NNT ignoré en mode %s", args.mode)
    finally:
        conn.close()


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
