"""Point d'entrée CLI : normalisation HAL."""

import os

from application.pipeline.normalize.normalize_hal import HalNormalizer
from infrastructure.addresses import PgAddressLinker
from infrastructure.app_config import get_api_base_urls
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.normalize_hal import PgHalNormalizeQueries
from infrastructure.db.queries.staging import PgStagingQueries
from infrastructure.log import setup_logger
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)
from infrastructure.zenodo import HttpZenodoResolver

logger = setup_logger("normalize_hal", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_connection()
    with conn.cursor() as cur:
        zenodo_api = get_api_base_urls(cur)["zenodo"]
    HalNormalizer(
        conn,
        logger,
        PgStagingQueries(),
        PgHalNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        zenodo_resolver=HttpZenodoResolver(api_base=zenodo_api),
        address_linker=PgAddressLinker(),
    ).run()


if __name__ == "__main__":
    main()
