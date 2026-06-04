"""Point d'entrée CLI : résolution du concept DOI des source_publications Zenodo."""

import os

from application.pipeline.publications.resolve_zenodo_concept import run
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.zenodo_concept import PgZenodoConceptQueries
from infrastructure.sources.config import get_api_base_urls
from infrastructure.sources.zenodo import HttpZenodoResolver

logger = setup_logger("resolve_zenodo_concept", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        zenodo_api = get_api_base_urls(bootstrap)["zenodo"]
    conn = engine.connect()
    try:
        run(conn, PgZenodoConceptQueries(), HttpZenodoResolver(api_base=zenodo_api), logger)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
