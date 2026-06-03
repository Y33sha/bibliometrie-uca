"""Point d'entrée CLI : normalisation OpenAlex."""

import os

from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.normalize_authorships import PgAuthorshipsBatchQueries
from infrastructure.queries.normalize_openalex import PgOpenalexNormalizeQueries
from infrastructure.queries.staging import PgStagingQueries
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)

logger = setup_logger("normalize_openalex", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_sync_engine().connect()
    OpenalexNormalizer(
        conn,
        logger,
        PgStagingQueries(),
        PgOpenalexNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        authorship_queries=PgAuthorshipsBatchQueries(),
    ).run()


if __name__ == "__main__":
    main()
