"""Point d'entrée CLI : peuplement de `person_name_forms`."""

import os

from application.pipeline.persons.populate_person_name_forms import populate
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.name_forms import PgNameFormsQueries

logger = setup_logger("populate_person_name_forms", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_sync_engine().connect()
    try:
        populate(conn, PgNameFormsQueries(), logger)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
