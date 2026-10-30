"""Modèles de réponse : lectures sur les structures.

`StructureOut` et `NameFormOut` composent aussi la réponse des écritures sur les structures.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, cast

from application.ports.model import Model
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

    `perimeter_ids` et `perimeter_none` se combinent en OU.
    """

    search: str = ""
    types: list[str] = field(default_factory=list)
    tutelle_ids: list[int] = field(default_factory=list)
    perimeter_ids: list[int] = field(default_factory=list)
    """Périmètres des structures retenues, sous-structures comprises."""
    perimeter_none: bool = False
    """Retient les structures hors de tout périmètre."""


class StructureListItem(Model):
    """Ligne résumée d'une structure, dans la liste paginée et dans le référentiel complet."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    hal_collection: str | None
    perimeter_ids: list[int]
    """Périmètres qui contiennent la structure, directement ou par une tutelle ; vide hors de tout périmètre."""
    tutelles: list[RelatedStructureOut] | None
    """Tutelles de la structure."""


class StructureListResponse(PaginatedResponse):
    structures: list[StructureListItem]


class StructuresFacetsResponse(Model):
    """Facettes de la liste des structures. Chaque décompte écarte le filtre de sa propre facette."""

    types: list[FacetOption]
    """Options sans libellé, résolu par le client."""
    tutelles: list[FacetOption]
    perimeters: list[FacetOption]
    """Options terminées par l'option `none`, hors de tout périmètre."""


class StructureOut(Model):
    """Structure complète, renvoyée par GET, POST et PUT sur `/api/structures`."""

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
        """Renvoie la réponse d'une structure enregistrée : son type sous le nom `type`, ses identifiants ROR et HAL en chaînes."""
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


class RelatedStructureOut(Model):
    """Structure voisine (tutelle ou sous-structure) dans le détail d'une structure."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    tutelle_id: int


class NameFormOut(Model):
    """Forme de nom d'une structure."""

    id: int
    structure_id: int
    form_text: str
    is_word_boundary: bool
    is_excluding: bool
    requires_context_of: list[int] | None
    created_at: datetime | None = None


class StructureDetailResponse(Model):
    """Détail complet renvoyé par GET /api/structures/{id}."""

    structure: StructureOut
    parents: list[RelatedStructureOut]
    children: list[RelatedStructureOut]
    forms: list[NameFormOut]
    theses_count: int


class StructureAddressOut(Model):
    id: int
    raw_text: str
    is_confirmed: bool | None


class StructureAddressesResponse(PaginatedResponse):
    addresses: list[StructureAddressOut]


class StructurePartner(Model):
    """Organisation partenaire d'une structure : un ROR des auteurs de ses publications."""

    ror_id: str
    name: str | None
    """Nom du référentiel ROR ; absent quand le ROR est plus récent que le référentiel importé."""
    country_code: str | None
    country_name: str | None
    types: list[str]
    publications: int
    """Nombre de copublications."""


class PartnerFacetOption(Model):
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


class StructureDeletionImpact(Model):
    """Données supprimées avec une structure."""

    name_forms: int
    tutelles: int
    confirmed_links: int
    rejected_links: int
    perimeter_codes: list[str]
