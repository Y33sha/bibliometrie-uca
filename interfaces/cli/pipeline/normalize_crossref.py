"""Point d'entrée CLI : normalisation CrossRef."""

import os

from application.pipeline.normalize.normalize_crossref import CrossrefNormalizer
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queries.normalize_crossref import PgCrossrefNormalizeQueries
from infrastructure.db.queries.staging import PgStagingQueries
from infrastructure.log import setup_logger
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)

logger = setup_logger("normalize_crossref", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_sync_engine().connect()
    CrossrefNormalizer(
        conn,
        logger,
        PgStagingQueries(),
        PgCrossrefNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
    ).run()


if __name__ == "__main__":
    main()
