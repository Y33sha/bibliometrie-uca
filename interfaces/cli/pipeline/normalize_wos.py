"""Point d'entrée CLI : normalisation Web of Science."""

import os

from application.pipeline.normalize.normalize_wos import WosNormalizer
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.normalize_wos import PgWosNormalizeQueries
from infrastructure.db.queries.staging import PgStagingQueries
from infrastructure.log import setup_logger
from infrastructure.repositories import journal_repository

logger = setup_logger("normalize_wos", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_connection()
    WosNormalizer(
        conn,
        logger,
        PgStagingQueries(),
        PgWosNormalizeQueries(),
        journal_repo_factory=journal_repository,
    ).run()


if __name__ == "__main__":
    main()
