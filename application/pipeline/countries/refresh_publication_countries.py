"""
Recalcule publications.countries à partir des 3 sources.

Trois étapes orchestrées via le port `CountryQueries` :
  1. HAL : source_structures.country → source_publications.countries
  2. OA/WoS/ScanR : addresses.countries → source_publications.countries
  3. Union de tous les source_publications.countries → publications.countries

Cet orchestrateur ne dépend que du domaine et de son port ; le point
d'entrée CLI (argparse + connexion + instanciation de l'adapter) est
dans `interfaces/cli/pipeline/refresh_publication_countries.py`.
"""

import time
from typing import Any

from application.ports.countries import CountryQueries


def refresh(conn: Any, queries: CountryQueries, logger: Any) -> int:
    t0 = time.perf_counter()

    hal_updated = queries.refresh_hal_source_countries(conn)
    logger.info(f"HAL documents countries : {hal_updated} mis à jour")

    addr_updated = queries.refresh_address_source_countries(conn)
    logger.info(f"OA/WoS/ScanR documents countries : {addr_updated} mis à jour")

    updated = queries.refresh_publication_countries(conn)
    elapsed = time.perf_counter() - t0
    logger.info(f"{updated} publications mises à jour en {elapsed:.1f}s")
    return updated
