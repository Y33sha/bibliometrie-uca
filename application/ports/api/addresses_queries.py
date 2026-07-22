"""Port : lectures sur les adresses (consommé par le router addresses).

Implémenté par `infrastructure.queries.api.addresses.PgAddressesQueries`.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel

from application.ports.api._common import PaginatedResponse

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


@dataclass(frozen=True, slots=True)
class AddressCountriesFilters:
    search: str = ""
    has_country: bool | None = None
    country_code: str = ""
    suggested_country: str = ""
    suggest: bool = False


# ----- DTOs de retour -----


class AddressStructureSummary(BaseModel):
    """Lien adresse ↔ structure (élément de `structures` dans la liste/review)."""

    id: int
    name: str
    acronym: str | None
    is_confirmed: bool | None
    is_detected: bool


class StructureLinkState(BaseModel):
    """État d'un lien adresse ↔ structure : détection automatique et arbitrage manuel.

    `is_confirmed` : `None` en attente d'arbitrage, `True` confirmé, `False` rejeté.
    """

    is_confirmed: bool | None
    is_detected: bool


class AddressOut(BaseModel):
    """Ligne de `/api/addresses` (liste paginée pour validation)."""

    id: int
    raw_text: str
    is_confirmed: bool | None
    is_detected: bool
    structures: list[AddressStructureSummary]
    pub_count: int


class AddressListResponse(PaginatedResponse):
    """Réponse paginée de `/api/addresses`.

    `requires_search=True` signale que le garde-fou du router a court-circuité la lecture et rendu une liste vide : la combinaison de filtres demandée porte sur toute la base plutôt que sur une structure, faute d'un prédicat de texte ou de structure pour la réduire.
    """

    addresses: list[AddressOut]
    requires_search: bool = False


class AddressPublicationItem(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doi: str | None
    doc_type: str
    journal_title: str | None
    author_name: str | None
    source_id: str | None


class CountrySuggestion(BaseModel):
    code: str
    count: int


class AddressForCountryAttribution(BaseModel):
    """Ligne de `/api/addresses/countries`."""

    id: int
    raw_text: str
    countries: list[str] | None
    suggested_countries: list[CountrySuggestion]
    pub_count: int


class AddressesCountriesResponse(PaginatedResponse):
    addresses: list[AddressForCountryAttribution]
    suggestion_facets: list[CountrySuggestion] | None = None
    country_facets: list[CountrySuggestion]


class AddressStatsResponse(BaseModel):
    """Compteurs d'adresses d'une structure, par état de détection et de validation."""

    total: int
    detected: int
    pending: int
    rejected: int
    confirmed: int


# ----- Port -----


class AddressesQueries(Protocol):
    """Lectures sur les adresses."""

    def list_addresses(
        self,
        *,
        structure_id: int,
        filters: AddressListFilters,
        page: int,
        per_page: int,
    ) -> AddressListResponse: ...

    def address_exists(self, addr_id: int) -> bool: ...

    def get_address_raw_text(self, addr_id: int) -> str | None:
        """Texte brut de l'adresse ; `None` signale une adresse absente, la colonne étant obligatoire."""
        ...

    def get_address_publications(
        self, addr_id: int, limit: int
    ) -> list[AddressPublicationItem]: ...

    def get_address_structures(self, addr_id: int) -> list[AddressStructureSummary]: ...

    def get_structure_link(self, addr_id: int, structure_id: int) -> StructureLinkState | None: ...

    def addresses_countries(
        self, *, filters: AddressCountriesFilters, page: int, per_page: int
    ) -> AddressesCountriesResponse: ...

    def address_stats(self, structure_id: int) -> AddressStatsResponse: ...
