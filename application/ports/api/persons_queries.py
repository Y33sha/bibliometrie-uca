"""Port : lectures sur les personnes (consommé par le router persons).

Les DTOs Pydantic sont co-localisés avec le `Protocol` (cf. décision 3
du chantier typage-projections-strict). Implémenté par
`infrastructure.queries.api.persons.PgPersonsQueries`.

Les dataclasses `DirectoryFilters` / `ListFilters` / `FacetFilters`
vivent ici (source de vérité) ; les fonctions infra les importent
depuis ce module pour typer leurs signatures (cf. règle 3
d'`architecture.md`).
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel

from application.ports.api._common import (
    DashboardOa,
    FacetValueCount,
    PubYearCount,
    StructureRef,
    ValueConfirmedOut,
    YesNoCount,
)
from application.ports.api.subjects_queries import SubjectFrequency


@dataclass(frozen=True, slots=True)
class DirectoryFilters:
    search: str = ""
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: str = ""
    has_idhal: str = ""
    has_idref: str = ""
    has_rh: str = ""
    # Scope facultatif à un laboratoire (onglet personnes de la fiche labo).
    lab_id: int | None = None


@dataclass(frozen=True, slots=True)
class ListFilters:
    search: str = ""
    department: str = ""
    role: str = ""
    has_orcid: str = ""
    has_idhal: str = ""
    has_idref: str = ""
    has_rh: str = ""


@dataclass(frozen=True, slots=True)
class FacetFilters:
    search: str = ""
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: str = ""
    has_idhal: str = ""
    has_idref: str = ""
    has_rh: str = ""
    # Scope facultatif à un laboratoire (onglet personnes de la fiche labo).
    lab_id: int | None = None


# ---------------------------------------------------------------------------
# DTOs Identifiants + formes de noms (réutilisés dans plusieurs réponses)
# ---------------------------------------------------------------------------


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
    status: Literal["pending", "confirmed", "rejected"]
    shared_count: int
    pub_count: int


# ---------------------------------------------------------------------------
# DTOs Annuaire / recherche / liste admin
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DTOs Facettes / référentiels / stats
# ---------------------------------------------------------------------------


class PersonsFacetsResponse(BaseModel):
    """Réponse de `/api/persons/facets`."""

    departments: list[FacetValueCount]
    roles: list[FacetValueCount]
    orcid: YesNoCount
    idhal: YesNoCount
    idref: YesNoCount
    rh: YesNoCount


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


# ---------------------------------------------------------------------------
# DTOs Détail d'une personne
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DTOs Admin : name forms (utilisés par `name_form_authorships`)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DTOs Triage : formes de nom ambiguës
# ---------------------------------------------------------------------------


class AmbiguousFormPersonOut(BaseModel):
    person_id: int
    first_name: str
    last_name: str
    status: Literal["pending", "confirmed", "rejected"]
    has_rh: bool
    # Nom canonique compatible (par tokens) avec la forme : homonyme/doublon si
    # vrai, erreur d'attribution probable si faux.
    compatible: bool


class AmbiguousNameFormOut(BaseModel):
    name_form: str
    persons: list[AmbiguousFormPersonOut]


class AmbiguousNameFormsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    forms: list[AmbiguousNameFormOut]


# ---------------------------------------------------------------------------
# DTOs Admin : authorships orphelines
# ---------------------------------------------------------------------------


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


class PersonsQueries(Protocol):
    """Lectures sync pour /api/persons/* + endpoints admin associés."""

    # ── Annuaire / recherche / liste admin ─────────────────────────

    def persons_directory(
        self, *, filters: DirectoryFilters, page: int, per_page: int, sort: str
    ) -> PersonDirectoryResponse: ...

    def search_persons(self, *, q: str, limit: int) -> list[PersonSearchResult]: ...

    def list_persons(
        self, *, filters: ListFilters, page: int, per_page: int, sort: str
    ) -> PersonListResponse: ...

    def person_admin(self, person_id: int) -> PersonOut | None: ...

    # ── Facettes / listes de référence / stats ─────────────────────

    def persons_facets(self, *, filters: FacetFilters) -> PersonsFacetsResponse: ...

    def list_departments(self) -> list[DepartmentCount]: ...

    def list_roles(self) -> list[RoleCount]: ...

    def persons_stats(self) -> PersonsStatsResponse: ...

    # ── Détail d'une personne ──────────────────────────────────────

    def person_profile(self, person_id: int) -> PersonProfileResponse | None: ...

    def person_theses(self, person_id: int) -> PersonThesesResponse: ...

    def person_addresses(
        self, person_id: int, *, page: int, per_page: int
    ) -> PersonAddressesResponse: ...

    def person_dashboard(self, person_id: int) -> PersonDashboardResponse: ...

    def person_subjects(self, person_id: int, *, limit: int) -> list[SubjectFrequency]: ...

    # ── Admin : existence, orphan authorships, name forms ──────────

    def person_exists(self, person_id: int) -> bool: ...

    def orphan_authorships_count(self) -> OrphanCountResponse: ...

    def list_orphan_authorships(
        self, *, search: str, page: int, per_page: int
    ) -> OrphanAuthorshipsResponse: ...

    def name_form_authorships(
        self, person_id: int, name_form: str
    ) -> NameFormAuthorshipsResponse: ...

    def ambiguous_name_forms_count(self) -> int: ...

    def ambiguous_name_forms(self, *, page: int, per_page: int) -> AmbiguousNameFormsResponse: ...
