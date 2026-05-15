"""Modèles Pydantic pour les adresses (validation, pays, propagation)."""

from pydantic import BaseModel

# ----- Entrées -----


class ReviewAction(BaseModel):
    structure_id: int
    is_confirmed: bool | None  # True = confirmé, False = rejeté, None = reset


class BatchReviewAction(BaseModel):
    address_ids: list[int]
    structure_id: int
    is_confirmed: bool | None


class AssignStructureAction(BaseModel):
    structure_id: int


class SetCountry(BaseModel):
    countries: list[str] | None = None


class BatchSetCountry(BaseModel):
    country_code: str
    address_ids: list[int] | None = None
    search: str = ""
    has_country: str = ""
    country_code_filter: str = ""
    suggested_country: str = ""


# ----- Sorties -----


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

    `requires_search=True` quand le caller utilise un filtre trop large
    (no/all + pas de search) et que le serveur a renvoyé une liste vide
    par garde-fou.
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


class AssignStructureResponse(BaseModel):
    id: int
    structure_id: int
    status: str


class UnassignStructureResponse(BaseModel):
    deleted: bool


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
