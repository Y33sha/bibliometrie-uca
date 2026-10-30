"""Modèles de réponse : lectures sur les adresses."""

from dataclasses import dataclass
from typing import Literal

from application.ports.model import Model
from domain.country_detection import CountryDetectionMethod
from infrastructure.read_models._common import FacetOption, PaginatedResponse

# État de détection d'un rattachement adresse-structure, et état de son arbitrage manuel.
AddressDetected = Literal["all", "yes", "no"]
AddressValidation = Literal["all", "pending", "confirmed", "rejected"]

# Vocabulaires des prédicats composables de la liste d'adresses.
TextPredicateMode = Literal["contains", "not_contains"]
StructurePredicateOperator = Literal["recognized", "not_recognized"]


@dataclass(frozen=True, slots=True)
class TextPredicate:
    """Filtre sur le texte brut de l'adresse."""

    mode: TextPredicateMode
    term: str


@dataclass(frozen=True, slots=True)
class StructurePredicate:
    """Filtre « structure reconnue » multi-structures.

    `recognized` retient les adresses reconnues comme au moins une des `structure_ids`, `not_recognized` les adresses reconnues comme aucune. Une adresse est reconnue comme une structure dès que le lien existe, en attente de validation ou confirmé.
    """

    operator: StructurePredicateOperator
    structure_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AddressListFilters:
    detected: AddressDetected = "yes"
    validation: AddressValidation = "pending"
    text_predicates: tuple[TextPredicate, ...] = ()
    structure_predicates: tuple[StructurePredicate, ...] = ()


# ----- Réponses -----


class AddressStructureSummary(Model):
    """Lien entre une adresse et une structure, dans la liste des adresses."""

    id: int
    name: str
    acronym: str | None
    is_confirmed: bool | None
    is_detected: bool


class StructureLinkState(Model):
    """État d'un lien entre adresse et structure : détection automatique et arbitrage manuel."""

    is_confirmed: bool | None
    """`None` en attente, vrai si confirmé, faux si rejeté."""
    is_detected: bool


class AddressOut(Model):
    """Ligne de `/api/addresses` (liste paginée pour validation)."""

    id: int
    raw_text: str
    is_confirmed: bool | None
    is_detected: bool
    structures: list[AddressStructureSummary]
    publication_count: int


class AddressListResponse(PaginatedResponse):
    """Réponse paginée de `/api/addresses`."""

    addresses: list[AddressOut]
    requires_search: bool = False
    """Vrai pour une liste vide renvoyée sans lecture : sans prédicat de texte ou de structure, les filtres demandés couvriraient toute la base."""


class AddressPublicationItem(Model):
    id: int
    title: str
    publication_year: int | None
    doi: str | None
    doc_type: str
    journal_title: str | None
    author_name: str | None
    source_id: str | None


class FoundCountry(Model):
    """Pays trouvé pour une adresse, avec ses moyens de détection."""

    country_code: str
    methods: list[CountryDetectionMethod]


class AddressForCountryAttribution(Model):
    """Ligne de `/api/addresses/countries`."""

    id: int
    raw_text: str
    countries: list[str] | None
    """Pays retenus."""
    found_countries: list[FoundCountry]
    """Tous les pays trouvés, retenus ou non."""
    publication_count: int


class AddressesCountriesResponse(PaginatedResponse):
    """Réponse paginée de `/api/addresses/countries`."""

    addresses: list[AddressForCountryAttribution]
    country_facets: list[FacetOption]
    without_country: int
    """Nombre d'adresses sans pays retenu, sous les mêmes filtres que `country_facets`."""


class AddressStatsResponse(Model):
    """Compteurs d'adresses d'une structure, par état de détection et de validation."""

    total: int
    detected: int
    pending: int
    rejected: int
    confirmed: int
