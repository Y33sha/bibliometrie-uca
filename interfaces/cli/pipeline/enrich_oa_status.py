"""Point d'entrée CLI : enrichissement OA via Unpaywall."""

import argparse
import os

from application.pipeline.enrich.enrich_oa_status import run_enrich
from infrastructure.api_limits import UNPAYWALL_DELAY
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.enrich import PgEnrichQueries
from infrastructure.log import setup_logger

logger = setup_logger("enrich_oa_unpaywall", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=0, help="Nombre max de publis à traiter (0=toutes)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Afficher sans modifier la base")
    args = parser.parse_args()

    conn = get_connection()
    try:
        cur = conn.cursor()
        run_enrich(
            cur,
            conn,
            PgEnrichQueries(),
            logger,
            limit=args.limit,
            dry_run=args.dry_run,
            rate_delay=UNPAYWALL_DELAY,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
