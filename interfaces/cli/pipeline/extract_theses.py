"""Point d'entrée CLI : extraction theses.fr."""

import os

from application.pipeline.extract.extract_theses import ThesesExtractor
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.staging import PgStagingQueries
from infrastructure.sources.config import get_api_base_urls
from infrastructure.sources.theses.extract_theses import PgThesesExtractAdapter

logger = setup_logger("extract_theses", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        base_url = get_api_base_urls(bootstrap).get(
            "theses", "https://theses.fr/api/v1/theses/recherche/"
        )
    conn = engine.connect()
    adapter = PgThesesExtractAdapter(base_url=base_url)
    ThesesExtractor(conn, logger, PgStagingQueries(), adapter).run()


if __name__ == "__main__":
    main()
