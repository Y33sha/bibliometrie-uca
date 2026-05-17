"""Point d'entrée CLI : normalisation ScanR."""

import os

from application.pipeline.normalize.normalize_scanr import ScanrNormalizer
from infrastructure.addresses import PgAddressLinker
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.normalize_scanr import PgScanrNormalizeQueries
from infrastructure.queries.staging import PgStagingQueries
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)

logger = setup_logger("normalize_scanr", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_sync_engine().connect()
    ScanrNormalizer(
        conn,
        logger,
        PgStagingQueries(),
        PgScanrNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        address_linker=PgAddressLinker(),
    ).run()


if __name__ == "__main__":
    main()
