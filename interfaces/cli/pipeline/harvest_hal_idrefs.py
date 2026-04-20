"""Point d'entrée CLI : moissonnage IdRef depuis HAL ref/author."""

import argparse
import os

from application.pipeline.harvest.harvest_hal_idrefs import run_harvest
from infrastructure.api_limits import HAL_DELAY
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.harvest import PgHarvestQueries
from infrastructure.log import setup_logger

logger = setup_logger("harvest_hal_idrefs", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    try:
        cur = conn.cursor()
        run_harvest(
            cur, conn, PgHarvestQueries(), logger, dry_run=args.dry_run, rate_delay=HAL_DELAY
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
