"""Port : lectures sur les laboratoires (consommé par le router laboratories).

Les DTOs Pydantic sont co-localisés avec le `Protocol` (cf. décision 3
du chantier typage-projections-strict). Implémenté par
`infrastructure.queries.api.laboratories.PgLaboratoriesQueries`.
"""

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from application.ports.api._common import (
    DashboardOa,
    FacetValueCount,
    PubYearCount,
    ValueConfirmedOut,
    YesNoCount,
)
from application.ports.api.subjects_queries import SubjectFrequency


@dataclass(frozen=True, slots=True)
class LabPersonsFilters:
    search: str = ""
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_rh: str = ""
    has_orcid: str = ""
    has_idhal: str = ""
    has_idref: str = ""


# ---------------------------------------------------------------------------
# DTOs renvoyés par les query services labos
# ---------------------------------------------------------------------------


class LabTutelle(BaseModel):
    """Tutelle d'un labo (établissement, EPST, etc.) dans la liste."""

    id: int
    name: str
    acronym: str | None
    type: str


class LaboratoryListItem(BaseModel):
    """Ligne de `/api/laboratories` (liste du périmètre)."""

    id: int
    code: str
    name: str
    acronym: str | None
    ror_id: str | None
    hal_collection: str | None
    tutelles: list[LabTutelle] | None


class LabStructureCore(BaseModel):
    """Métadonnées du labo (bloc `structure` du détail)."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None


class LabRelatedStructure(BaseModel):
    """Structure voisine (tutelle, sous-labo) dans le détail d'un labo.

    Distinct de `RelatedStructureOut` (utilisé pour les structures
    génériques) — pas de `code` ni `relation_id` côté labo.
    """

    id: int
    name: str
    acronym: str | None
    type: str
    relation_type: str


class LaboratoryDetailResponse(BaseModel):
    structure: LabStructureCore
    parents: list[LabRelatedStructure]
    children: list[LabRelatedStructure]
    theses_count: int


class LabPersonOut(BaseModel):
    """Personne liée à un labo (onglet `persons`)."""

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


class LabPersonsFacets(BaseModel):
    departments: list[FacetValueCount]
    roles: list[FacetValueCount]
    rh: YesNoCount
    orcid: YesNoCount
    idhal: YesNoCount
    idref: YesNoCount


class LaboratoryPersonsResponse(BaseModel):
    total_persons: int
    page: int
    per_page: int
    pages: int
    persons: list[LabPersonOut]
    facets: LabPersonsFacets


class LabAddressOut(BaseModel):
    id: int
    raw_text: str
    is_confirmed: bool | None


class LaboratoryAddressesResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    addresses: list[LabAddressOut]


class LabDashboardCollab(BaseModel):
    total_articles: int
    international: int
    domestic: int


class LabTopCountry(BaseModel):
    code: str
    name: str
    count: int


class LaboratoryDashboardResponse(BaseModel):
    pubs_by_year: list[PubYearCount]
    oa: DashboardOa
    collab: LabDashboardCollab
    top_countries: list[LabTopCountry]


class LaboratoriesQueries(Protocol):
    """Lectures sur les laboratoires."""

    def list_laboratories(self) -> list[LaboratoryListItem]: ...

    def get_laboratory(self, lab_id: int) -> LaboratoryDetailResponse | None: ...

    def get_laboratory_persons(
        self,
        lab_id: int,
        *,
        filters: LabPersonsFilters,
        page: int,
        per_page: int,
        sort: str,
    ) -> LaboratoryPersonsResponse: ...

    def get_laboratory_addresses(
        self, lab_id: int, *, page: int, per_page: int
    ) -> LaboratoryAddressesResponse: ...

    def get_laboratory_subjects(self, lab_id: int, *, limit: int) -> list[SubjectFrequency]: ...

    def get_laboratory_dashboard(self, lab_id: int) -> LaboratoryDashboardResponse: ...
