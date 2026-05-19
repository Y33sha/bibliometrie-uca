"""Point d'entrée CLI : peuplement `in_perimeter`/`structure_ids`."""

import argparse
import os

from application.pipeline.affiliations.populate_affiliations import run_populate, show_stats
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.affiliations import PgAffiliationsQueries
from infrastructure.queries.perimeter import (
    get_affiliations_structure_ids,
    get_persons_structure_ids,
)

logger = setup_logger("populate_affiliations", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Peuplement in_perimeter et structure_ids")
    parser.add_argument("--stats", action="store_true", help="Stats uniquement")
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "weekly", "daily"],
        help="Mode d'exécution (daily: incrémental, autres: complet)",
    )
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        queries = PgAffiliationsQueries()

        if args.stats:
            show_stats(conn, queries, logger)
            return

        perimeter_ids = get_persons_structure_ids(conn)
        wide_ids = get_affiliations_structure_ids(conn)
        run_populate(
            conn,
            queries,
            logger,
            perimeter_ids,
            wide_ids,
            mode=args.mode,
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
