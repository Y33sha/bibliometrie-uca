"""Modèles Pydantic (bodies + réponses router-only) pour les adresses.

Les DTOs retournés par le port `AddressesQueries` (AddressOut, AddressListResponse, AddressStructureSummary, AddressPublicationItem, CountryOut, CountrySuggestion, AddressForCountryAttribution, AddressesCountriesResponse, CountrySuggestionsResponse, AddressStatsResponse) vivent dans `application/ports/api/addresses_queries.py` (cf. chantier `CODE_typage-projections-strict` Phase 4). Restent ici les bodies HTTP et les réponses composées par le router.
"""

from pydantic import BaseModel

from application.ports.api.addresses_queries import (
    AddressPublicationItem,
    AddressStructureSummary,
)

# ----- Bodies HTTP -----


class ReviewAction(BaseModel):
    structure_id: int
    is_confirmed: bool | None  # True = confirmé, False = rejeté, None = reset


class BatchReviewAction(BaseModel):
    address_ids: list[int]
    structure_id: int
    is_confirmed: bool | None


class SetCountry(BaseModel):
    countries: list[str] | None = None


class BatchSetCountry(BaseModel):
    country_code: str
    address_ids: list[int] | None = None
    search: str = ""
    has_country: str = ""
    country_code_filter: str = ""
    suggested_country: str = ""


# ----- Réponses composées par le router -----


class AddressPublicationsResponse(BaseModel):
    address_id: int
    raw_text: str
    publications: list[AddressPublicationItem]


class AddressReviewResponse(BaseModel):
    """Réponse de POST /api/addresses/{addr_id}/review."""

    id: int
    is_confirmed: bool | None
    is_detected: bool
    structures: list[AddressStructureSummary]


class BatchCountryResponse(BaseModel):
    """POST /api/addresses/batch-country : modifs directes + propagation."""

    updated: int
    propagated: int
