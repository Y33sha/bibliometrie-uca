"""Point d'entrée CLI : normalisation CrossRef."""

import os

from application.pipeline.normalize.normalize_crossref import CrossrefNormalizer
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.normalize_crossref import PgCrossrefNormalizeQueries
from infrastructure.queries.staging import PgStagingQueries
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)
from infrastructure.repositories.address_linker import PgAddressLinker

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
        address_linker=PgAddressLinker(),
    ).run()


if __name__ == "__main__":
    main()
