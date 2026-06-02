"""Point d'entrée CLI : construction de la table `authorships`."""

import argparse
import os

from application.pipeline.authorships.build_authorships import build
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.authorships_build import PgAuthorshipsBuildQueries

logger = setup_logger("build_authorships", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier la base")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        build(conn, PgAuthorshipsBuildQueries(), logger)

        if args.dry_run:
            conn.rollback()
            logger.info("DRY-RUN — aucune modification.")
        else:
            conn.commit()
            logger.info("COMMIT effectué.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
