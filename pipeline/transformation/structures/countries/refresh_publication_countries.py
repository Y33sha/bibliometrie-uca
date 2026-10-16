"""Recalcule les pays des signatures, des notices et des publications.

Trois caches dénormalisés orchestrés via le port `CountryQueries`, bornés aux lignes `countries_dirty` :
  1. `source_authorships.countries` — pays retenus des adresses de la signature, pays de ses organisations ROR sans adresse et de ses structures HAL.
  2. `source_publications.countries` — union des `source_authorships.countries` du document.
  3. `publications.countries` — union des `source_publications.countries` de même publication_id.
"""

import logging
import time

from sqlalchemy import Connection

from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.structures.countries.countries_queries import CountryQueries


def refresh(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> int:
    """Recalcule les caches pays (source_authorships → source_publications → publications), scopé aux `countries_dirty`, puis purge les flags. Retourne le nombre de publications mises à jour. Chaque étape a sa ligne de journal, avec son nombre de lignes et sa durée."""
    etape(logger, "Rafraîchissement des pays associés aux publications")
    steps = (
        ("signature", "signatures", queries.refresh_signature_countries),
        ("notice", "notices", queries.refresh_address_source_countries),
        ("publication", "publications", queries.refresh_publication_countries),
    )
    updated = 0
    for singular, plural, step in steps:
        t0 = time.perf_counter()
        with attente(f"{BRANCHE}{plural} : en cours", logger) as ligne:
            updated = step(conn)
            ligne.conclut(
                f"{BRANCHE}{accord(updated, f'{singular} mise à jour', f'{plural} mises à jour')}"
                f" en {time.perf_counter() - t0:.1f} s"
            )
    t0 = time.perf_counter()
    with attente(
        f"{DERNIERE_BRANCHE}effacement des marqueurs de recalcul : en cours", logger
    ) as ligne:
        queries.clear_countries_dirty(conn)
        ligne.conclut(
            f"{DERNIERE_BRANCHE}marqueurs de recalcul effacés en {time.perf_counter() - t0:.1f} s"
        )
    return updated
