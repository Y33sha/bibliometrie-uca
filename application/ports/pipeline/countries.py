"""Port : recalcul, par le pipeline, des pays des notices et des publications d'un lot d'adresses, après une modification manuelle de leurs pays.

Implémenté par `pipeline.transformation.structures.countries.countries_queries.CountryQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class CountryRecompute(Protocol):
    """Recalcul ciblé des caches de pays à partir de `addresses.countries`."""

    def refresh_source_publications_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
        """Recalcule `source_publications.countries` (union des pays des adresses de leurs signatures) pour les documents rattachés à l'une des `address_ids`. Idempotent. Retourne le nombre de documents mis à jour."""
        ...

    def refresh_publications_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
        """Recalcule `publications.countries` (union des `source_publications.countries`) pour les publications rattachées à l'une des `address_ids`. Idempotent. Retourne le nombre de publications mises à jour."""
        ...
