"""Point d'entrée CLI : extraction OpenAlex."""

import os

from application.pipeline.extract.extract_openalex import OpenalexExtractor
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.config import get_api_base_urls
from infrastructure.sources.openalex.extract_openalex import PgOpenalexExtractAdapter

logger = setup_logger("extract_openalex", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        base_url = get_api_base_urls(bootstrap)["openalex"]
    conn = engine.connect()
    adapter = PgOpenalexExtractAdapter(base_url=base_url)
    OpenalexExtractor(conn, logger, adapter).run()


if __name__ == "__main__":
    main()
