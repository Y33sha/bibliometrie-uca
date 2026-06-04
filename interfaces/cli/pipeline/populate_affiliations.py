"""Point d'entrée CLI : peuplement `in_perimeter` + refresh matview structures."""

import argparse
import os

from application.pipeline.affiliations.populate_affiliations import run_populate, show_stats
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.perimeter import get_persons_structure_ids
from infrastructure.queries.pipeline.affiliations import PgAffiliationsQueries

logger = setup_logger("populate_affiliations", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Peuplement in_perimeter + refresh structures")
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
        run_populate(
            conn,
            queries,
            logger,
            perimeter_ids,
            mode=args.mode,
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
