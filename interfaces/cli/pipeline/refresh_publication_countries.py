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
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.countries import PgCountryQueries
from infrastructure.log import setup_logger

logger = setup_logger(
    "refresh_publication_countries", os.path.join(os.path.dirname(__file__), "logs")
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalcul des pays des publications")
    parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        refresh(cur, PgCountryQueries(), logger)
        conn.commit()
        logger.info("Terminé")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
