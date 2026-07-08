"""Point d'entrée CLI : création/mapping des personnes depuis les source_authorships."""

import argparse
import os

from application.pipeline.persons.phase import run
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.name_forms import PgNameFormsQueries
from infrastructure.queries.pipeline.persons_create import PgPersonsCreateQueries
from infrastructure.repositories import authorship_repository, person_repository

logger = setup_logger("create_persons", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crée des personnes à partir des authorships sources UCA"
    )
    parser.add_argument("--dry-run", action="store_true", help="Simuler sans modifier la base")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        run(
            conn,
            PgPersonsCreateQueries(),
            PgNameFormsQueries(),
            logger,
            person_repo=person_repository(conn),
            authorship_repo=authorship_repository(conn),
            dry_run=args.dry_run,
        )
        if args.dry_run:
            conn.rollback()
            logger.info("(dry-run — rien n'a été modifié)")
        else:
            conn.commit()
            logger.info("✓ Appliqué.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
