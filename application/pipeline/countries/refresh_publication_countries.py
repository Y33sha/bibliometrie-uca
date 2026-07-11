"""Recalcule `publications.countries` depuis `addresses.countries`.

Deux caches dénormalisés orchestrés via le port `CountryQueries`, chacun recalculé directement depuis les adresses, borné aux lignes `countries_dirty` :
  1. `source_publications.countries` — union des pays des adresses des source_authorships du document.
  2. `publications.countries` — union des `source_publications.countries` de même publication_id.
"""

import logging
import time

from sqlalchemy import Connection

from application.ports.pipeline.countries import CountryQueries


def refresh(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> int:
    """Recalcule les caches pays (source_publications → publications), scopé aux `countries_dirty`, puis purge les flags. Retourne le nombre de publications mises à jour."""
    t0 = time.perf_counter()

    # Étape 1 : source_publications.countries (documents dont un source_authorship est dirty)
    sp_updated = queries.refresh_address_source_countries(conn)
    logger.info(f"source_publications.countries : {sp_updated} mis à jour")

    # Étape 2 : publications.countries (dont un source_publication a un source_authorship dirty)
    updated = queries.refresh_publication_countries(conn)

    # Les flags `countries_dirty` (source_authorships + adresses) ont borné la portée des deux étapes : on les purge.
    queries.clear_countries_dirty(conn)

    elapsed = time.perf_counter() - t0
    logger.info(f"{updated} publications mises à jour en {elapsed:.1f}s")
    return updated
