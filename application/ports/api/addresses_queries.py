"""Port : lectures sur les adresses (consommé par le router addresses).

Implémenté par `infrastructure.queries.api.addresses.PgAddressesQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class TextPredicate:
    """Filtre texte sur `raw_text`. `mode` ∈ {contains, not_contains}."""

    mode: str
    term: str


@dataclass(frozen=True, slots=True)
class StructurePredicate:
    """Filtre « structure reconnue » multi-structures.

    `operator` ∈ {recognized, not_recognized}. Sémantique au sein du prédicat :
    `recognized` = reconnue comme **au moins une** des `structure_ids` (OR) ;
    `not_recognized` = reconnue comme **aucune** d'elles. « Reconnue » = lien
    pending ou confirmé (cf. `_RECOGNIZED_LINK` dans l'adapter).
    """

    operator: str
    structure_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AddressListFilters:
    detected: str = "yes"  # all, yes, no
    validation: str = "pending"  # all, pending, confirmed, rejected
    text_predicates: tuple[TextPredicate, ...] = ()
    structure_predicates: tuple[StructurePredicate, ...] = ()


@dataclass(frozen=True, slots=True)
class AddressCountriesFilters:
    search: str = ""
    has_country: str = ""  # "yes", "no", ""
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


class AddressOut(BaseModel):
    """Ligne de `/api/addresses` (liste paginée pour validation)."""

    id: int
    raw_text: str
    is_confirmed: bool | None
    is_detected: bool
    structures: list[AddressStructureSummary]
    pub_count: int


class AddressListResponse(BaseModel):
    """Réponse paginée de `/api/addresses`.

    `requires_search=True` quand le caller utilise un filtre trop large (no/all + pas de search) et que le serveur a renvoyé une liste vide par garde-fou.
    """

    total: int
    page: int
    per_page: int
    pages: int
    addresses: list[AddressOut]
    requires_search: bool | None = None


class AddressPublicationItem(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doi: str | None
    doc_type: str
    journal_title: str | None
    author_name: str | None
    source_id: str | None


class CountryOut(BaseModel):
    code: str
    name: str


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


class AddressesCountriesResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    addresses: list[AddressForCountryAttribution]
    suggestion_facets: list[CountrySuggestion] | None = None
    country_facets: list[CountrySuggestion]


class CountrySuggestionsResponse(BaseModel):
    """GET /api/addresses/suggest-countries (admin)."""

    suggestions: list[CountrySuggestion]
    without_country: int


class AddressStatsResponse(BaseModel):
    """GET /api/admin/address-stats."""

    total: int
    detected: int
    pending: int
    rejected: int
    confirmed: int


# ----- Port -----


class AddressesQueries(Protocol):
    """Lectures sync sur les adresses + pays."""

    def resolve_default_structure_id(self) -> int: ...

    def list_addresses(
        self,
        *,
        structure_id: int,
        filters: AddressListFilters,
        page: int,
        per_page: int,
    ) -> AddressListResponse: ...

    def get_address_raw_text(self, addr_id: int) -> str | None: ...

    def get_address_publications(
        self, addr_id: int, limit: int
    ) -> list[AddressPublicationItem]: ...

    def get_address_structures(self, addr_id: int) -> list[AddressStructureSummary]: ...

    # Les deux champs `is_confirmed` (Optional bool) et `is_detected` (bool) suffisent au router pour assembler la réponse review ; un mini-DTO serait surdimensionné. `dict[str, Any]` accepté ici en frontière.
    def get_structure_link(self, addr_id: int, structure_id: int) -> dict[str, Any] | None: ...

    def list_countries(self) -> list[CountryOut]: ...

    def country_exists(self, code: str) -> bool: ...

    def address_exists(self, addr_id: int) -> bool: ...

    def addresses_countries(
        self, *, filters: AddressCountriesFilters, page: int, per_page: int
    ) -> AddressesCountriesResponse: ...

    def suggest_countries(self, search: str) -> CountrySuggestionsResponse: ...

    def admin_address_stats(self, structure_id: int) -> AddressStatsResponse: ...
