"""Point d'entrée CLI : moissonnage ORCID + IdRef (batch) via HAL ref/author."""

import argparse
import os

from application.pipeline.normalize.harvest_hal_identifiers import run_harvest
from infrastructure.api_limits import HAL_DELAY
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.harvest import PgHarvestQueries
from infrastructure.log import setup_logger

logger = setup_logger("harvest_hal_identifiers", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Moissonnage ORCID + IdRef depuis l'API personnes HAL"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--batch", type=int, default=100, help="Nombre de person_ids par requête API (défaut: 100)"
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        run_harvest(
            cur,
            conn,
            PgHarvestQueries(),
            logger,
            batch_size=args.batch,
            dry_run=args.dry_run,
            rate_delay=HAL_DELAY,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
