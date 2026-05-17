"""Point d'entrée CLI : normalisation theses.fr."""

import os

from application.pipeline.normalize.normalize_theses import ThesesNormalizer
from infrastructure.addresses import PgAddressLinker
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.normalize_theses import PgThesesNormalizeQueries
from infrastructure.queries.staging import PgStagingQueries
from infrastructure.repositories import publication_repository

logger = setup_logger("normalize_theses", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_sync_engine().connect()
    ThesesNormalizer(
        conn,
        logger,
        PgStagingQueries(),
        PgThesesNormalizeQueries(),
        pub_repo_factory=publication_repository,
        address_linker=PgAddressLinker(),
    ).run()


if __name__ == "__main__":
    main()
