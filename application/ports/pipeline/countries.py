"""Port : résolution, par le pipeline, des pays d'un lot d'adresses, puis recalcul des pays de leurs enregistrements sources et publications, après une saisie manuelle.

Implémenté par `pipeline.transformation.countries.refresh_publication_countries.CountryRecompute`.
"""

from typing import Protocol


class CountryRecompute(Protocol):
    """Résolution des pays d'adresses, et recalcul ciblé des caches de pays à partir de `addresses.countries`."""

    def resolve_address_countries(self, address_ids: list[int]) -> int:
        """Compose les pays des adresses données à partir de leurs candidats, par la préséance du domaine. Renvoie le nombre d'adresses modifiées."""
        ...

    def refresh_source_records_countries_for_addresses(self, address_ids: list[int]) -> int:
        """Recalcule les pays des enregistrements sources rattachés à ces adresses : union des pays des adresses de leurs contributions sources. Renvoie le nombre d'enregistrements sources modifiés."""
        ...

    def refresh_publications_countries_for_addresses(self, address_ids: list[int]) -> int:
        """Recalcule les pays des publications rattachées à ces adresses : union des pays de leurs enregistrements sources. Renvoie le nombre de publications modifiées."""
        ...
