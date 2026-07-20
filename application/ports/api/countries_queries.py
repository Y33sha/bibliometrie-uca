"""Port : lecture du référentiel des pays (consommé par le router countries).

Implémenté par `infrastructure.queries.api.countries.PgCountriesQueries`. Le référentiel sert les listes de choix partout où un pays s'attribue ou se filtre ; l'attribution elle-même porte sur des adresses et passe par `addresses_queries`.
"""

from typing import Protocol

from pydantic import BaseModel


class CountryOut(BaseModel):
    """Pays du référentiel : code ISO à deux lettres et libellé."""

    code: str
    name: str


class CountriesQueries(Protocol):
    """Lectures pour `/api/countries`."""

    def list_countries(self) -> list[CountryOut]: ...
