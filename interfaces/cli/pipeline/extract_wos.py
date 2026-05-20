"""Point d'entrée CLI : extraction WoS."""

import os

from application.pipeline.extract.extract_wos import WosExtractor
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.staging import PgStagingQueries
from infrastructure.sources.config import get_api_base_urls, get_wos_api_key
from infrastructure.sources.wos.extract_wos import PgWosExtractAdapter

logger = setup_logger("extract_wos", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        base_url = get_api_base_urls(bootstrap).get("wos", "https://api.clarivate.com/api/wos")
        api_key = get_wos_api_key(bootstrap)
    conn = engine.connect()
    adapter = PgWosExtractAdapter(base_url=base_url, api_key=api_key)
    WosExtractor(conn, logger, PgStagingQueries(), adapter).run()


if __name__ == "__main__":
    main()
