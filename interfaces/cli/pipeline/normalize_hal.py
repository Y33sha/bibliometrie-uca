"""Point d'entrée CLI : normalisation HAL."""

import os

from application.pipeline.normalize.normalize_hal import HalNormalizer
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
from infrastructure.queries.pipeline.normalize.hal import PgHalNormalizeQueries
from infrastructure.queries.pipeline.staging import PgStagingQueries
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)

logger = setup_logger("normalize_hal", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_sync_engine().connect()
    HalNormalizer(
        conn,
        logger,
        PgStagingQueries(),
        PgHalNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        authorship_queries=PgAuthorshipsBatchQueries(),
    ).run()


if __name__ == "__main__":
    main()
