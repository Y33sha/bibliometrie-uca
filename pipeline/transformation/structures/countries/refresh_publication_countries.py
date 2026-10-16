"""Recalcule les pays des signatures, des notices et des publications.

Trois caches dénormalisés orchestrés via le port `CountryQueries`, bornés aux lignes `countries_dirty` :
  1. `source_authorships.countries` — pays retenus des adresses de la signature, pays de ses organisations ROR sans adresse et de ses structures HAL.
  2. `source_publications.countries` — union des `source_authorships.countries` du document.
  3. `publications.countries` — union des `source_publications.countries` de même publication_id.
"""

import logging
import time

from sqlalchemy import Connection

from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, etape
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.structures.countries.countries_queries import CountryQueries


def refresh(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> int:
    """Recalcule les caches pays (source_authorships → source_publications → publications), scopé aux `countries_dirty`, puis purge les flags. Retourne le nombre de publications mises à jour."""
    etape(logger, "Rafraîchissement des pays associés aux publications")
    t0 = time.perf_counter()
    # Les recalculs balaient le stock marqué : la ligne dit le travail en cours, puis cède la
    # place à sa durée.
    with attente(f"{DERNIERE_BRANCHE}en cours", logger) as ligne:
        # Étape 1 : source_authorships.countries ; une signature modifiée est marquée pour la suite
        queries.refresh_signature_countries(conn)

        # Étape 2 : source_publications.countries (documents dont un source_authorship est dirty)
        queries.refresh_address_source_countries(conn)

        # Étape 3 : publications.countries (dont un source_publication a un source_authorship dirty)
        updated = queries.refresh_publication_countries(conn)

        # Les flags `countries_dirty` (source_authorships + adresses) ont borné la portée des deux étapes : on les purge.
        queries.clear_countries_dirty(conn)

        ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")
    return updated
