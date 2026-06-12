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


def refresh(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> int:
    t0 = time.perf_counter()

    # Étape 1 : sa.countries — uniquement les sa `countries_dirty`, en une seule
    # requête (plus de split par source : le LEFT JOIN orphelin absorbe le
    # cleanup, et le dirty-scoping borne le volume → pas de spill à éviter).
    t_sa = time.perf_counter()
    n_sa = queries.refresh_sa_countries(conn)
    logger.info(
        f"source_authorships.countries : {n_sa} mis à jour en {time.perf_counter() - t_sa:.1f}s"
    )

    # Étape 2 : sp.countries (documents dont un sa est dirty)
    addr_updated = queries.refresh_address_source_countries(conn)
    logger.info(f"source_publications.countries : {addr_updated} mis à jour")

    # Étape 3 : publications.countries (dont un sp a un sa dirty)
    updated = queries.refresh_publication_countries(conn)

    # Les flags `countries_dirty` (sa + adresses) ont borné la portée des 3
    # étapes : on les purge.
    queries.clear_countries_dirty(conn)

    elapsed = time.perf_counter() - t0
    logger.info(f"{updated} publications mises à jour en {elapsed:.1f}s")
    return updated
