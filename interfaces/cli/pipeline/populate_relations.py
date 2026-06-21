"""Point d'entrée CLI : population des relations entre publications."""

import os

from application.pipeline.relations.populate_relations import run
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.relations import PgPublicationRelationsQueries

logger = setup_logger("populate_relations", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_sync_engine().connect()
    try:
        run(conn, PgPublicationRelationsQueries(), logger)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
