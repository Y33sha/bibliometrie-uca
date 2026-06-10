"""
Point d'entrée CLI : résolution des adresses → structures.

Composition root.

Usage :
    python -m interfaces.cli.pipeline.resolve_addresses

Chaque exécution est un recalcul complet idempotent : toutes les adresses sont
re-matchées et seules les détections qui changent sont écrites.
"""

import os

from application.pipeline.affiliations.resolve_addresses import run_resolution
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.perimeter import get_persons_structure_ids
from infrastructure.queries.pipeline.address_resolution import PgAddressResolutionQueries

logger = setup_logger("resolve_addresses", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    conn = get_sync_engine().connect()
    try:
        perimeter_ids = get_persons_structure_ids(conn)
        run_resolution(conn, PgAddressResolutionQueries(), perimeter_ids, logger)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
