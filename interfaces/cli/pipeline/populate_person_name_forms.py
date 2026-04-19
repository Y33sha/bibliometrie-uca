"""Point d'entrée CLI : peuplement de `person_name_forms`."""

import os

from application.pipeline.build.populate_person_name_forms import populate
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.name_forms import PgNameFormsQueries
from infrastructure.log import setup_logger

logger = setup_logger("populate_person_name_forms", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        populate(cur, conn, PgNameFormsQueries(), logger)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
