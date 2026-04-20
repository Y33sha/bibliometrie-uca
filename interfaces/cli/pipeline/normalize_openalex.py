"""Point d'entrée CLI : normalisation OpenAlex."""

import os

from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.normalize_openalex import PgOpenalexNormalizeQueries
from infrastructure.db.queries.staging import PgStagingQueries
from infrastructure.log import setup_logger

logger = setup_logger("normalize_openalex", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_connection()
    OpenalexNormalizer(conn, logger, PgStagingQueries(), PgOpenalexNormalizeQueries()).run()


if __name__ == "__main__":
    main()
