"""
Point d'entrée CLI : recalcul des pays des publications.

Composition root : ouvre la connexion, instancie l'adapter SQL, appelle
l'orchestrateur `application.pipeline.countries.refresh_publication_countries.refresh`
et commit.

Usage :
    python -m interfaces.cli.pipeline.refresh_publication_countries
"""

import argparse
import os

from application.pipeline.countries.refresh_publication_countries import refresh
from infrastructure.db.engine import get_sync_engine
from infrastructure.log import setup_logger
from infrastructure.queries.countries import PgCountryQueries

logger = setup_logger(
    "refresh_publication_countries", os.path.join(os.path.dirname(__file__), "logs")
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalcul des pays des publications")
    parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        refresh(conn, PgCountryQueries(), logger)
        conn.commit()
        logger.info("Terminé")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
