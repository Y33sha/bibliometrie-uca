"""Modèles Pydantic du router des adresses : corps des requêtes entrantes et réponses composées après mutation."""

from application.ports.model import Model
from infrastructure.read_models.addresses.models import (
    AddressPublicationItem,
    AddressStructureSummary,
)

# ----- Corps des requêtes -----

# `is_confirmed` : vrai pour confirmé, faux pour rejeté, `None` pour revenir en attente.


class ReviewAction(Model):
    structure_id: int
    is_confirmed: bool | None


class BatchReviewAction(Model):
    address_ids: list[int]
    structure_id: int
    is_confirmed: bool | None


class SetCountry(Model):
    countries: list[str] | None = None


class BatchSetCountry(Model):
    country_code: str
    address_ids: list[int] | None = None
    search: str = ""
    has_country: bool | None = None
    country_code_filter: str = ""


# ----- Réponses composées par le router -----


class AddressPublicationsResponse(Model):
    """Publications rattachées à une adresse, avec le texte brut de celle-ci."""

    address_id: int
    raw_text: str
    publications: list[AddressPublicationItem]


class AddressReviewResponse(Model):
    """Réponse de POST /api/addresses/{addr_id}/review."""

    id: int
    is_confirmed: bool | None
    is_detected: bool
    structures: list[AddressStructureSummary]


class BatchCountryResponse(Model):
    """POST /api/addresses/batch-country : nombre d'adresses modifiées."""

    updated: int
