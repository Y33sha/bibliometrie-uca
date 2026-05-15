"""Modèles Pydantic pour les personnes (annuaire, profils, dédup, identifiants)."""

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

# ----- Entrées (POST/PUT/PATCH) -----


class LinkPersonAuthor(BaseModel):
    author_id: int
    source: str  # 'hal' or 'openalex'


class AddIdentifier(BaseModel):
    id_type: str  # 'orcid' or 'idhal'
    id_value: str


class UpdateIdentifierStatus(BaseModel):
    status: Literal["pending", "confirmed", "rejected"]


class ReassignIdentifier(BaseModel):
    person_id: int


class RejectPerson(BaseModel):
    rejected: bool = True


class UpdatePersonName(BaseModel):
    last_name: str
    first_name: str = ""


class MergePersons(BaseModel):
    source_id: int


class MarkPersonsDistinct(BaseModel):
    person_id_a: int
    person_id_b: int


class CreatePersonName(BaseModel):
    last_name: str
    first_name: str = ""


class SourceAuthorshipRef(BaseModel):
    source: str
    authorship_id: int


class AssignOrphanAuthorship(BaseModel):
    source: str
    authorship_id: int
    person_id: int | None = None
    create_person: CreatePersonName | None = None


class BatchAssignOrphanAuthorships(BaseModel):
    authorships: list[SourceAuthorshipRef]
    person_id: int


class DetachAuthorships(BaseModel):
    authorships: list[SourceAuthorshipRef]
    name_form: str = ""


class DetachNameForm(BaseModel):
    name_form: str


# ----- Sorties (annuaire, listing, profil) -----


class PersonIdentifierOut(BaseModel):
    """Identifiant (ORCID, idHAL, idRef) attaché à une personne."""

    id: int
    id_type: str
    id_value: str
    source: str
    status: Literal["pending", "confirmed", "rejected"]


class LinkedAuthorOut(BaseModel):
    """Auteur source (HAL/OpenAlex/WoS) lié à une personne."""

    id: int
    source: str
    full_name: str


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


class PersonDetail(BaseModel):
    """Réponse de `/api/persons/{id}` (détail + auteurs liés)."""

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
    linked_authors: list[LinkedAuthorOut] | None
    identifiers: list[PersonIdentifierOut] | None


class PersonProfileCore(BaseModel):
    """Bloc `person` de `/api/persons/{id}/profile`."""

    id: int
    last_name: str
    first_name: str
    role_title: str | None
    department_name: str | None
    start_date: date | None
    end_date: date | None


class PersonProfileAuthor(BaseModel):
    """Auteur source dans `/api/persons/{id}/profile` (vue publique enrichie)."""

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


class NameFormAuthorshipRef(BaseModel):
    source: str
    authorship_id: int
    pub_id: int
    title: str
    pub_year: int | None
    doi: str | None


class OtherPersonOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    department_name: str | None
    has_rh: bool


class NameFormAuthorshipsResponse(BaseModel):
    authorships: list[NameFormAuthorshipRef]
    other_persons: list[OtherPersonOut]


class OrphanCountResponse(BaseModel):
    total: int


class OrphanAuthorshipOut(BaseModel):
    source: str
    authorship_id: int
    full_name: str
    last_name: str
    first_name: str
    publication_id: int
    pub_title: str
    pub_year: int | None


class OrphanAuthorshipsResponse(BaseModel):
    total: int
    page: int
    pages: int
    authorships: list[OrphanAuthorshipOut]


class PersonDashboardResponse(BaseModel):
    pubs_by_year: list[PubYearCount]
    oa: DashboardOa


# ----- Réponses mutations -----


class AddIdentifierResponse(BaseModel):
    """Réponse de `POST /api/persons/{id}/identifiers`.

    Polymorphe selon le chemin :
    - doublon exact : `added=False` + `reason`
    - ajout normal  : `added=True` + `id_type` + `id_value`
    - réattribution : en plus, `reassigned=True`
    """

    added: bool
    reason: str | None = None
    id_type: str | None = None
    id_value: str | None = None
    reassigned: bool | None = None


class IdentifierStatusResponse(BaseModel):
    id: int
    status: str


class IdentifierReassignResponse(BaseModel):
    id: int
    person_id: int
    status: str


class AuthorshipExcludeResponse(BaseModel):
    id: int
    excluded: bool


class OrphanAssignResponse(BaseModel):
    ok: bool = True
    person_id: int


class OrphanBatchAssignResponse(BaseModel):
    ok: bool = True
    assigned: int


class DetachAuthorshipsResponse(BaseModel):
    detached: int
    deleted_authorships: int
    cleaned_form: bool
