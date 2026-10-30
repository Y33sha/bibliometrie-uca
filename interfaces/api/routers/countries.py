"""Router du référentiel des pays. Sert `/api/countries`.

Le référentiel alimente les listes de choix partout où un pays s'attribue ou se filtre. Le router `addresses.py` sert l'attribution des pays aux adresses.
"""

from fastapi import APIRouter, Depends

from infrastructure.read_models.countries.models import (
    CountryOut,
)
from infrastructure.read_models.countries.queries import CountriesQueries
from interfaces.api.deps import countries_queries

router = APIRouter(prefix="/api/countries", tags=["countries"])


@router.get("", response_model=list[CountryOut])
def list_countries(
    queries: CountriesQueries = Depends(countries_queries),
) -> list[CountryOut]:
    """Renvoie le référentiel des pays, pour les listes de choix de l'attribution."""
    return queries.list_countries()
