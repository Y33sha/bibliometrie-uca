"""Router du référentiel des pays. Sert `/api/countries`.

Le référentiel alimente les listes de choix partout où un pays s'attribue ou se filtre. L'attribution elle-même porte sur des adresses et vit dans le router `addresses.py`.
"""

from fastapi import APIRouter, Depends

from application.ports.api.addresses_queries import AddressesQueries, CountryOut
from interfaces.api.deps import addresses_queries

router = APIRouter(prefix="/api/countries", tags=["countries"])


@router.get("", response_model=list[CountryOut])
def list_countries(
    queries: AddressesQueries = Depends(addresses_queries),
) -> list[CountryOut]:
    """Référentiel des pays, servant les listes de choix de l'attribution."""
    return queries.list_countries()
