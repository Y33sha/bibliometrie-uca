"""Modèles de réponse : lectures sur les adresses."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

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

    `recognized` retient les adresses reconnues comme au moins une des `structure_ids`, `not_recognized` celles qui ne le sont comme aucune d'elles. Une adresse est reconnue comme une structure dès que le lien existe, qu'il soit en attente de validation ou confirmé.
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


class AddressStructureSummary(BaseModel):
    """Lien entre une adresse et une structure, dans la liste des adresses."""

    id: int
    name: str
    acronym: str | None
    is_confirmed: bool | None
    is_detected: bool


class StructureLinkState(BaseModel):
    """État d'un lien entre adresse et structure : détection automatique et arbitrage manuel. `is_confirmed` : `None` en attente, vrai si confirmé, faux si rejeté."""

    is_confirmed: bool | None
    is_detected: bool


class AddressOut(BaseModel):
    """Ligne de `/api/addresses` (liste paginée pour validation)."""

    id: int
    raw_text: str
    is_confirmed: bool | None
    is_detected: bool
    structures: list[AddressStructureSummary]
    publication_count: int


class AddressListResponse(PaginatedResponse):
    """Réponse paginée de `/api/addresses`.

    `requires_search` vrai signale une liste vide rendue sans lecture : sans prédicat de texte ou de structure, les filtres demandés couvriraient toute la base.
    """

    addresses: list[AddressOut]
    requires_search: bool = False


class AddressPublicationItem(BaseModel):
    id: int
    title: str
    publication_year: int | None
    doi: str | None
    doc_type: str
    journal_title: str | None
    author_name: str | None
    source_id: str | None


class FoundCountry(BaseModel):
    """Pays trouvé pour une adresse, et les moyens de détection qui le trouvent."""

    country_code: str
    methods: list[CountryDetectionMethod]


class AddressForCountryAttribution(BaseModel):
    """Ligne de `/api/addresses/countries`. `countries` : pays retenus. `found_countries` : tous les pays trouvés, retenus ou non."""

    id: int
    raw_text: str
    countries: list[str] | None
    found_countries: list[FoundCountry]
    publication_count: int


class AddressesCountriesResponse(PaginatedResponse):
    """`without_country` : nombre d'adresses sans pays retenu, sous les mêmes filtres que `country_facets`."""

    addresses: list[AddressForCountryAttribution]
    country_facets: list[FacetOption]
    without_country: int


class AddressStatsResponse(BaseModel):
    """Compteurs d'adresses d'une structure, par état de détection et de validation."""

    total: int
    detected: int
    pending: int
    rejected: int
    confirmed: int


# ----- Port -----
