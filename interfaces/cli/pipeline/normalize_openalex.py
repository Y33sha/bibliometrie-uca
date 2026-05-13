"""Point d'entrée CLI : normalisation OpenAlex."""

import os

from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
from infrastructure.addresses import PgAddressLinker
from infrastructure.app_config import get_api_base_urls
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queries.normalize_openalex import PgOpenalexNormalizeQueries
from infrastructure.db.queries.staging import PgStagingQueries
from infrastructure.log import setup_logger
from infrastructure.repositories import (
    journal_repository,
    publication_repository,
    publisher_repository,
)
from infrastructure.sources.zenodo import HttpZenodoResolver

logger = setup_logger("normalize_openalex", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        zenodo_api = get_api_base_urls(bootstrap)["zenodo"]
    conn = engine.connect()
    OpenalexNormalizer(
        conn,
        logger,
        PgStagingQueries(),
        PgOpenalexNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        zenodo_resolver=HttpZenodoResolver(api_base=zenodo_api),
        address_linker=PgAddressLinker(),
    ).run()


if __name__ == "__main__":
    main()
