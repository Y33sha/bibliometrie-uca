"""Port : lectures sur les structures.

Implémenté par `infrastructure.read_models.structures.PgStructuresQueries`.

`StructureOut` et `NameFormOut` composent aussi la réponse des écritures sur les structures.
"""

from datetime import datetime
from typing import Protocol, cast

from pydantic import BaseModel

from application.ports.read_models._common import (
    DashboardOa,
    PaginatedResponse,
    PublicationYearCount,
)
from application.ports.read_models.subjects_queries import SubjectFrequency
from domain.structures.structure import Structure


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

    @classmethod
    def from_structure(cls, structure: Structure) -> "StructureOut":
        """Réponse d'une structure enregistrée : son type sous le nom `type`, ses identifiants ROR et HAL en chaînes."""
        return cls(
            id=cast(int, structure.id),
            code=structure.code,
            name=structure.name,
            acronym=structure.acronym,
            type=structure.structure_type.value,
            ror_id=structure.ror_id.value if structure.ror_id else None,
            rnsr_id=structure.rnsr_id,
            hal_collection=structure.hal_collection.value if structure.hal_collection else None,
            api_ids=structure.api_ids,
        )


class RelatedStructureOut(BaseModel):
    """Structure voisine (parent/enfant) dans le détail d'une structure."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    relation_id: int


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
    """Articles de la structure, selon qu'ils comportent ou non une affiliation étrangère."""

    total_articles: int
    international: int
    domestic: int


class StructureTopCountry(BaseModel):
    code: str
    name: str
    count: int


class StructureDashboardResponse(BaseModel):
    publications_by_year: list[PublicationYearCount]
    oa: DashboardOa
    collab: StructureCollaborations
    top_countries: list[StructureTopCountry]


class StructurePartner(BaseModel):
    """Organisation partenaire d'une structure : un ROR des auteurs de ses publications, avec le nombre de copublications."""

    ror_id: str
    name: str | None
    """Nom du référentiel ROR ; absent quand le ROR est plus récent que le référentiel importé."""
    country_code: str | None
    country_name: str | None
    types: list[str]
    publications: int


class PartnerFacetOption(BaseModel):
    value: str
    label: str
    count: int


class StructurePartnersResponse(PaginatedResponse):
    """Organisations partenaires d'une structure, les plus fréquentes en tête, et les options de leurs filtres."""

    partners: list[StructurePartner]
    years: list[PartnerFacetOption]
    """Années des copublications, chacune avec son nombre de publications."""
    countries: list[PartnerFacetOption]
    types: list[PartnerFacetOption]


class StructureDeletionImpact(BaseModel):
    """Ce que la suppression d'une structure emporte."""

    name_forms: int
    tutelles: int
    confirmed_links: int
    rejected_links: int
    perimeter_codes: list[str]


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

    def get_structure_partners(
        self,
        structure_id: int,
        *,
        years: list[int],
        countries: list[str],
        types: list[str],
        page: int,
        per_page: int,
    ) -> StructurePartnersResponse:
        """Organisations partenaires des publications de la structure (`publication_rors`), hors ses propres ROR et ceux de ses tutelles, ancêtres compris."""
        ...

    def get_name_form(self, form_id: int) -> NameFormOut | None: ...

    def get_deletion_impact(self, structure_id: int) -> StructureDeletionImpact | None:
        """Formes de nom, tutelles, liens adresse-structure confirmés ou rejetés, et périmètres dont la structure est une racine. `None` si la structure n'existe pas."""
        ...
