"""
Point d'entrée CLI : résolution des adresses → structures.

Composition root.

Usage :
    python -m interfaces.cli.pipeline.resolve_addresses          # tout
    python -m interfaces.cli.pipeline.resolve_addresses --reset  # reset auto
    python -m interfaces.cli.pipeline.resolve_addresses --rerun  # reset + full
    python -m interfaces.cli.pipeline.resolve_addresses --mode daily
"""

import argparse
import os

from application.pipeline.affiliations.resolve_addresses import run_resolution
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.perimeter import get_persons_structure_ids
from infrastructure.queries.pipeline.address_resolution import PgAddressResolutionQueries

logger = setup_logger("resolve_addresses", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Supprime les affiliations auto")
    parser.add_argument(
        "--rerun", action="store_true", help="Reset auto puis relance la résolution complète"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "weekly", "daily"],
        default="full",
        help="Mode d'exécution (daily = incrémental)",
    )
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        perimeter_ids = get_persons_structure_ids(conn)
        run_resolution(
            conn,
            PgAddressResolutionQueries(),
            perimeter_ids,
            logger,
            mode=args.mode,
            reset=args.reset,
            rerun=args.rerun,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
