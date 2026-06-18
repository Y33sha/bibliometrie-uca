"""Point d'entrée CLI : re-fetch des works OpenAlex tronqués (>= 100 auteurs)."""

from __future__ import annotations

import argparse
import asyncio
import os

from application.pipeline.extract.refetch_truncated import refetch
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.openalex.refetch_truncated import PgOpenalexRefetchAdapter

logger = setup_logger("refetch_truncated", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-fetch publications OA tronquées (>= 100 auteurs)"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, help="Nombre max de works à traiter")
    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "Cible les works déjà normalisés (comptés sur source_publications) "
            "et non les seules lignes staging non normalisées."
        ),
    )
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    adapter = PgOpenalexRefetchAdapter()
    try:
        asyncio.run(
            refetch(conn, adapter, logger, dry_run=args.dry_run, limit=args.limit, full=args.full)
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
