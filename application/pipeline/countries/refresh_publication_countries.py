"""
Recalcule publications.countries en cascade depuis les addresses.countries.

Trois caches dénormalisés orchestrés via le port `CountryQueries` :
  1. addresses.countries → source_authorships.countries
  2. source_authorships.countries → source_publications.countries
     (toutes sources passent par les adresses, circuit unifié)
  3. source_publications.countries → publications.countries

Cet orchestrateur ne dépend que du domaine et de son port ; le point
d'entrée CLI (argparse + connexion + instanciation de l'adapter) est
dans `interfaces/cli/pipeline/refresh_publication_countries.py`.
"""

import logging
import time

from sqlalchemy import Connection

from application.ports.pipeline.countries import CountryQueries
from domain.sources import ALL_SOURCES


def refresh(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> int:
    t0 = time.perf_counter()

    # Étape 1 : sa.countries — batché par source (évite le spill sur disque
    # du GROUP BY agrégé sur 7M rows en une seule passe).
    for source in ALL_SOURCES:
        t_source = time.perf_counter()
        n = queries.refresh_sa_countries_for_source(conn, source)
        logger.info(
            f"source_authorships.countries[{source}] : {n} mis à jour "
            f"en {time.perf_counter() - t_source:.1f}s"
        )
    # Pass 2 : nettoyer les sa polluées (countries non-NULL sans adresses utiles)
    t_cleanup = time.perf_counter()
    n_cleanup = queries.cleanup_sa_countries_orphans(conn)
    logger.info(
        f"source_authorships.countries cleanup : {n_cleanup} polluées remises à NULL "
        f"en {time.perf_counter() - t_cleanup:.1f}s"
    )

    # Étape 2 : sp.countries
    addr_updated = queries.refresh_address_source_countries(conn)
    logger.info(f"source_publications.countries : {addr_updated} mis à jour")

    # Étape 3 : publications.countries
    updated = queries.refresh_publication_countries(conn)
    elapsed = time.perf_counter() - t0
    logger.info(f"{updated} publications mises à jour en {elapsed:.1f}s")
    return updated
