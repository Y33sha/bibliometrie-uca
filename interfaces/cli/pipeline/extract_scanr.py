"""Point d'entrée CLI : extraction ScanR."""

import os

from application.pipeline.extract.extract_scanr import ScanrExtractor
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.config import get_api_base_urls
from infrastructure.sources.scanr.extract_scanr import (
    PgScanrExtractAdapter,
    get_scanr_credentials_from_db,
)

logger = setup_logger("extract_scanr", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        base_url = get_api_base_urls()["scanr"]
        credentials = get_scanr_credentials_from_db(bootstrap)
    conn = engine.connect()
    adapter = PgScanrExtractAdapter(base_url=base_url, credentials=credentials)
    ScanrExtractor(conn, logger, adapter).run()


if __name__ == "__main__":
    main()
