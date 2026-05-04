"""Point d'entrée CLI : peuplement `in_perimeter`/`structure_ids`."""

import argparse
import os

from application.pipeline.affiliations.populate_affiliations import run_populate, show_stats
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.affiliations import PgAffiliationsQueries
from infrastructure.log import setup_logger
from infrastructure.perimeter import get_affiliations_structure_ids, get_persons_structure_ids

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

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        queries = PgAffiliationsQueries()

        if args.stats:
            show_stats(cur, queries, logger)
            return

        perimeter_ids = get_persons_structure_ids(cur)
        wide_ids = get_affiliations_structure_ids(cur)
        run_populate(
            cur,
            conn,
            queries,
            logger,
            perimeter_ids,
            wide_ids,
            mode=args.mode,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
