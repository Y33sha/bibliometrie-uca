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
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.address_resolution import PgAddressResolutionQueries
from infrastructure.log import setup_logger
from infrastructure.perimeter import get_persons_structure_ids

logger = setup_logger("resolve_addresses", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Supprime les affiliations auto")
    parser.add_argument(
        "--rerun", action="store_true", help="Reset auto puis relance la résolution complète"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "weekly", "monthly", "daily"],
        default="full",
        help="Mode d'exécution (daily = incrémental)",
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        perimeter_ids = get_persons_structure_ids(cur)
        run_resolution(
            cur,
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
