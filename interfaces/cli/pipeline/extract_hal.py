"""Point d'entrée CLI : extraction HAL."""

import os

from application.pipeline.extract.extract_hal import HalExtractor
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.config import get_api_base_urls
from infrastructure.sources.hal.extract_hal import PgHalExtractAdapter

logger = setup_logger("extract_hal", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    engine = get_sync_engine()
    hal_url = get_api_base_urls()["hal"]
    conn = engine.connect()
    adapter = PgHalExtractAdapter(base_url=hal_url)
    HalExtractor(conn, logger, adapter).run()


if __name__ == "__main__":
    main()
