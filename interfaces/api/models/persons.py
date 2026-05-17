"""Modèles Pydantic pour les personnes (annuaire public, profils, listes)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from interfaces.api.models._common import (
    DashboardOa,
    FacetValueCount,
    PubYearCount,
    StructureRef,
    ValueConfirmedOut,
    YesNoCount,
)


class PersonIdentifierOut(BaseModel):
    """Identifiant (ORCID, idHAL, idRef) attaché à une personne."""

    id: int
    id_type: str
    id_value: str
    source: str
    status: Literal["pending", "confirmed", "rejected"]


class NameFormSummaryOut(BaseModel):
    """Forme de nom observée pour une personne (liste admin)."""

    name_form: str
    sources: list[str]
    ambiguous: bool


class PersonDirectoryEntry(BaseModel):
    """Ligne de l'annuaire public `/api/persons/directory`."""

    id: int
    last_name: str
    first_name: str
    role_title: str | None
    department_name: str | None
    has_rh: bool
    pub_count: int
    orcids: list[ValueConfirmedOut] | None
    idhals: list[ValueConfirmedOut] | None
    idrefs: list[ValueConfirmedOut] | None


class PersonDirectoryResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    persons: list[PersonDirectoryEntry]


class PersonSearchResult(BaseModel):
    """Résultat d'autocomplete `/api/persons/search`."""

    id: int
    last_name: str
    first_name: str
    department_name: str | None
    has_rh: bool


class PersonOut(BaseModel):
    """Ligne de `/api/persons` (liste admin)."""

    id: int
    last_name: str
    first_name: str
    last_name_normalized: str
    first_name_normalized: str
    role_title: str | None
    department_name: str | None
    start_date: date | None
    end_date: date | None
    has_rh: bool
    rejected: bool
    pub_count: int
    uca_pub_count: int
    identifiers: list[PersonIdentifierOut] | None
    name_forms: list[NameFormSummaryOut] | None


class PersonListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    persons: list[PersonOut]


class PersonsFacetsResponse(BaseModel):
    """Réponse de `/api/persons/facets`."""

    departments: list[FacetValueCount]
    roles: list[FacetValueCount]
    orcid: YesNoCount
    idhal: YesNoCount
    idref: YesNoCount
    rh: YesNoCount
    linked: YesNoCount


class DepartmentCount(BaseModel):
    department_name: str
    count: int


class RoleCount(BaseModel):
    role_title: str
    count: int


class PersonsStatsResponse(BaseModel):
    total_persons: int
    linked_persons: int
    linked_authors: int
    departments: int


class PersonProfileCore(BaseModel):
    """Bloc `person` de `/api/persons/{id}`."""

    id: int
    last_name: str
    first_name: str
    role_title: str | None
    department_name: str | None
    start_date: date | None
    end_date: date | None


class PersonProfileAuthor(BaseModel):
    """Auteur source dans `/api/persons/{id}` (vue publique enrichie)."""

    id: int
    source: str
    full_name: str | None
    orcid: str | None
    idhal: str | None
    hal_person_id: int | None = None
    openalex_id: str | None
    uca_pub_count: int


class PersonProfileResponse(BaseModel):
    person: PersonProfileCore
    identifiers: list[PersonIdentifierOut]
    authors: list[PersonProfileAuthor]
    theses_count: int


class PersonThesis(BaseModel):
    id: int
    title: str
    pub_year: int | None
    doi: str | None
    author_name: str | None
    author_person_id: int | None
    structure_ids: list[int]


class PersonThesesSection(BaseModel):
    role: str
    label: str
    theses: list[PersonThesis]


class PersonThesesResponse(BaseModel):
    sections: list[PersonThesesSection]
    total: int
    structures: dict[int, StructureRef]


class PersonAddressStruct(BaseModel):
    id: int
    acronym: str | None
    name: str


class PersonAddressOut(BaseModel):
    id: int
    raw_text: str
    structures: list[PersonAddressStruct] | None


class PersonAddressesResponse(BaseModel):
    total: int
    page: int
    pages: int
    addresses: list[PersonAddressOut]


class PersonDashboardResponse(BaseModel):
    pubs_by_year: list[PubYearCount]
    oa: DashboardOa
