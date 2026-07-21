"""Modèles Pydantic du router des adresses : corps des requêtes entrantes et réponses composées après mutation."""

from pydantic import BaseModel

from application.ports.api.addresses_queries import (
    AddressPublicationItem,
    AddressStructureSummary,
)

# ----- Corps des requêtes -----

# `is_confirmed` : True = confirmé, False = rejeté, None = retour à l'état non tranché.


class ReviewAction(BaseModel):
    structure_id: int
    is_confirmed: bool | None


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
    has_country: bool | None = None
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
