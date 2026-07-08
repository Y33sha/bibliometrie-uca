"""Point d'entrée CLI : création/mapping des personnes depuis les source_authorships."""

import argparse
import os

from application.pipeline.persons.cascade import create, match
from application.pipeline.persons.reset import reset
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
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
        # Réapplique les épinglages admin (must-link) avant la cascade : une
        # signature épinglée (`confirmed_authorships`) reste sur sa personne, le
        # pipeline ne la re-dérive pas.
        n_enforced = authorship_repository(conn).enforce_confirmed_authorships()
        if n_enforced:
            logger.info("Épinglages réappliqués : %d signatures recalées", n_enforced)

        q, repo = PgPersonsCreateQueries(), person_repository(conn)
        reset(conn, q, logger, person_repo=repo)
        match(conn, q, logger, person_repo=repo, dry_run=args.dry_run)
        create(conn, q, logger, person_repo=repo, dry_run=args.dry_run)
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
