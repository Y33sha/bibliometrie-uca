"""Recalcule `publications.countries` depuis `addresses.countries`.

Deux caches dénormalisés orchestrés via le port `CountryQueries`, chacun recalculé directement depuis les adresses, borné aux lignes `countries_dirty` :
  1. `source_publications.countries` — union des pays des adresses des source_authorships du document.
  2. `publications.countries` — union des `source_publications.countries` de même publication_id.
"""

import logging
import time

from sqlalchemy import Connection

from application.pipeline.libelles import DERNIERE_BRANCHE, etape
from application.pipeline.progression import attente
from application.ports.pipeline.countries import CountryQueries


def refresh(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> int:
    """Recalcule les caches pays (source_publications → publications), scopé aux `countries_dirty`, puis purge les flags. Retourne le nombre de publications mises à jour."""
    etape(logger, "Rafraîchissement des pays associés aux publications")
    t0 = time.perf_counter()
    # Les deux recalculs balaient le stock marqué : la ligne dit le travail en cours, puis cède la
    # place à sa durée.
    with attente(f"{DERNIERE_BRANCHE}en cours", logger) as ligne:
        # Étape 1 : source_publications.countries (documents dont un source_authorship est dirty)
        queries.refresh_address_source_countries(conn)

        # Étape 2 : publications.countries (dont un source_publication a un source_authorship dirty)
        updated = queries.refresh_publication_countries(conn)

        # Les flags `countries_dirty` (source_authorships + adresses) ont borné la portée des deux étapes : on les purge.
        queries.clear_countries_dirty(conn)

        ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")
    return updated
