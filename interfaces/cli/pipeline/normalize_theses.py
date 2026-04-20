"""Point d'entrée CLI : normalisation theses.fr."""

import os

from application.pipeline.normalize.normalize_theses import ThesesNormalizer
from infrastructure.addresses import PgAddressLinker
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.normalize_theses import PgThesesNormalizeQueries
from infrastructure.db.queries.staging import PgStagingQueries
from infrastructure.log import setup_logger
from infrastructure.repositories import publication_repository

logger = setup_logger("normalize_theses", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_connection()
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
