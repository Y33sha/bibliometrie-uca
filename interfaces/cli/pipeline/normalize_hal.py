"""Point d'entrée CLI : normalisation HAL."""

import os

from application.pipeline.normalize.normalize_hal import HalNormalizer
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.normalize_hal import PgHalNormalizeQueries
from infrastructure.db.queries.staging import PgStagingQueries
from infrastructure.log import setup_logger

logger = setup_logger("normalize_hal", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_connection()
    HalNormalizer(conn, logger, PgStagingQueries(), PgHalNormalizeQueries()).run()


if __name__ == "__main__":
    main()
