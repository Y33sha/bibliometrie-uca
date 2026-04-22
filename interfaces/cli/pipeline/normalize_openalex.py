"""Point d'entrée CLI : normalisation OpenAlex."""

import os

from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
from infrastructure.addresses import PgAddressLinker
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.normalize_openalex import PgOpenalexNormalizeQueries
from infrastructure.db.queries.staging import PgStagingQueries
from infrastructure.log import setup_logger
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)
from infrastructure.zenodo import HttpZenodoResolver

logger = setup_logger("normalize_openalex", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_connection()
    OpenalexNormalizer(
        conn,
        logger,
        PgStagingQueries(),
        PgOpenalexNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        zenodo_resolver=HttpZenodoResolver(),
        address_linker=PgAddressLinker(),
    ).run()


if __name__ == "__main__":
    main()
