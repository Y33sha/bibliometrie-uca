"""Modèles de réponse : lectures sur les structures.

`StructureOut` et `NameFormOut` composent aussi la réponse des écritures sur les structures.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel

from domain.structures.structure import Structure
from infrastructure.read_models._common import (
    FacetOption,
    PaginatedResponse,
)

StructureSort = Literal[
    "acronym_asc",
    "acronym_desc",
    "name_asc",
    "name_desc",
    "tutelles_asc",
    "tutelles_desc",
]


@dataclass(frozen=True, slots=True)
class StructureFilters:
    """Filtres de la liste des structures, de ses facettes et de son export.

    `perimeter_ids` retient les structures de ces périmètres, clôture comprise. `perimeter_none` retient les structures hors de tout périmètre. Les deux se combinent en OU.
    """

    search: str = ""
    types: list[str] = field(default_factory=list)
    tutelle_ids: list[int] = field(default_factory=list)
    perimeter_ids: list[int] = field(default_factory=list)
    perimeter_none: bool = False


class StructureListItem(BaseModel):
    """Ligne résumée d'une structure, dans la liste paginée et dans le référentiel complet."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    hal_collection: str | None
    perimeter_ids: list[int]
    """Périmètres auxquels la structure appartient (clôture transitive). Vide = hors périmètre."""
    tutelles: list[RelatedStructureOut] | None
    """Structures qui exercent une tutelle sur celle-ci."""


class StructureListResponse(PaginatedResponse):
    structures: list[StructureListItem]


class StructuresFacetsResponse(BaseModel):
    """Facettes de la liste des structures.

    `types` laisse le libellé au client. `tutelles` et `perimeters` donnent le libellé de la structure ou du périmètre ; `perimeters` se termine par l'option `none`, hors de tout périmètre. Chaque décompte écarte le filtre de sa propre facette.
    """

    types: list[FacetOption]
    tutelles: list[FacetOption]
    perimeters: list[FacetOption]


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
    def from_structure(cls, structure: Structure) -> StructureOut:
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
