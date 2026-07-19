"""Port : lectures sur les structures (consommé par le router structures).

Implémenté par `infrastructure.queries.api.structures.PgStructuresQueries`.

Le router importe `StructureOut` et `NameFormOut` pour valider les dicts que lui rendent les services applicatifs (`create_structure`, `update_structure`, `create_name_form`…), au-delà des lectures de ce port.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from application.ports.api._common import DashboardOa, PaginatedResponse, PubYearCount
from application.ports.api.subjects_queries import SubjectFrequency


class StructureListItem(BaseModel):
    """Ligne résumée de `/api/structures` (liste + recherche)."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    hal_collection: str | None
    perimeter_ids: list[int]
    """Périmètres auxquels la structure appartient (clôture transitive). Vide = hors périmètre."""
    tutelles: list["RelatedStructureOut"] | None
    """Structures qui exercent une tutelle sur celle-ci."""


class StructureOut(BaseModel):
    """Structure complète — renvoyée par GET/POST/PUT sur `/api/structures`."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None
    api_ids: dict[str, list[str]] | None


class RelatedStructureOut(BaseModel):
    """Structure voisine (parent/enfant) dans le détail d'une structure."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    relation_id: int
    relation_type: str


class NameFormOut(BaseModel):
    """Forme de nom d'une structure."""

    id: int
    structure_id: int
    form_text: str
    is_word_boundary: bool
    is_excluding: bool
    requires_context_of: list[int] | None
    created_at: datetime | None = None


class StructureDetailResponse(BaseModel):
    """Détail complet renvoyé par GET /api/structures/{id}."""

    structure: StructureOut
    parents: list[RelatedStructureOut]
    children: list[RelatedStructureOut]
    forms: list[NameFormOut]
    theses_count: int


class StructureAddressOut(BaseModel):
    id: int
    raw_text: str
    is_confirmed: bool | None


class StructureAddressesResponse(PaginatedResponse):
    addresses: list[StructureAddressOut]


class StructureCollaborations(BaseModel):
    """Articles de la structure, selon qu'ils portent ou non une affiliation étrangère."""

    total_articles: int
    international: int
    domestic: int


class StructureTopCountry(BaseModel):
    code: str
    name: str
    count: int


class StructureDashboardResponse(BaseModel):
    pubs_by_year: list[PubYearCount]
    oa: DashboardOa
    collab: StructureCollaborations
    top_countries: list[StructureTopCountry]


class StructuresQueries(Protocol):
    """Lectures sur les structures, relations et formes de noms."""

    def list_structures(
        self, *, types: list[str], search: str, in_perimeter: bool
    ) -> list[StructureListItem]: ...

    def get_structure_detail(self, structure_id: int) -> StructureDetailResponse | None: ...

    def get_structure_addresses(
        self, structure_id: int, *, page: int, per_page: int
    ) -> StructureAddressesResponse: ...

    def get_structure_subjects(
        self, structure_id: int, *, limit: int
    ) -> list[SubjectFrequency]: ...

    def get_structure_dashboard(self, structure_id: int) -> StructureDashboardResponse: ...

    def get_name_form(self, form_id: int) -> NameFormOut | None: ...
