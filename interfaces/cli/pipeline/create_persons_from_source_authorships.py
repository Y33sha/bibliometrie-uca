"""Point d'entrée CLI : création/mapping des personnes depuis les source_authorships."""

import argparse
import os

from application.pipeline.persons.create_persons_from_source_authorships import run
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.persons.create import PgPersonsCreateQueries
from infrastructure.log import setup_logger
from infrastructure.repositories import person_repository

logger = setup_logger("create_persons", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crée des personnes à partir des authorships sources UCA"
    )
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier la base")
    args = parser.parse_args()

    conn = get_connection()
    try:
        cur = conn.cursor()
        run(
            cur,
            conn,
            PgPersonsCreateQueries(),
            logger,
            person_repo=person_repository(cur),
            dry_run=args.dry_run,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
