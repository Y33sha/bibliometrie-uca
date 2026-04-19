"""
Recalcule publications.countries à partir des 3 sources.

Trois étapes (SQL dans `infrastructure/db/queries/countries.py`) :
  1. HAL : source_structures.country → source_publications.countries
  2. OA/WoS/ScanR : addresses.countries → source_publications.countries
  3. Union de tous les source_publications.countries → publications.countries

Usage:
    python refresh_publication_countries.py              # recalculer
"""

import argparse
import os
import time
from typing import Any

from infrastructure.db.connection import get_connection
from infrastructure.db.queries.countries import (
    refresh_address_source_countries,
    refresh_hal_source_countries,
    refresh_publication_countries,
)
from infrastructure.log import setup_logger

logger = setup_logger(
    "refresh_publication_countries", os.path.join(os.path.dirname(__file__), "logs")
)


def refresh(cur: Any) -> int:
    t0 = time.perf_counter()

    hal_updated = refresh_hal_source_countries(cur)
    logger.info(f"HAL documents countries : {hal_updated} mis à jour")

    addr_updated = refresh_address_source_countries(cur)
    logger.info(f"OA/WoS/ScanR documents countries : {addr_updated} mis à jour")

    updated = refresh_publication_countries(cur)
    elapsed = time.perf_counter() - t0
    logger.info(f"{updated} publications mises à jour en {elapsed:.1f}s")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalcul des pays des publications")
    parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    refresh(cur)
    conn.commit()
    logger.info("Terminé")
    conn.close()


if __name__ == "__main__":
    main()
