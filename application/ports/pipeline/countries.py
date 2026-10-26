"""Port : résolution, par le pipeline, des pays d'un lot d'adresses, puis recalcul des pays de leurs enregistrements sources et publications, après une saisie manuelle.

Implémenté par `pipeline.transformation.countries.refresh_publication_countries.CountryRecompute`.
"""

from typing import Protocol


class CountryRecompute(Protocol):
    """Résolution des pays d'adresses, et recalcul ciblé des caches de pays à partir de `addresses.countries`."""

    def resolve_address_countries(self, address_ids: list[int]) -> int:
        """Compose `addresses.countries` des `address_ids` à partir de leurs candidats, par la préséance du domaine. Retourne le nombre d'adresses dont le pays change."""
        ...

    def refresh_source_records_countries_for_addresses(self, address_ids: list[int]) -> int:
        """Recalcule `source_records.countries` (union des pays des adresses de leurs contributions sources) pour les enregistrements sources rattachés à l'une des `address_ids`. Idempotent. Retourne le nombre d'enregistrements sources mis à jour."""
        ...

    def refresh_publications_countries_for_addresses(self, address_ids: list[int]) -> int:
        """Recalcule `publications.countries` (union des `source_records.countries`) pour les publications rattachées à l'une des `address_ids`. Idempotent. Retourne le nombre de publications mises à jour."""
        ...
