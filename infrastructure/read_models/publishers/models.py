"""Modèles de réponse : lectures sur les éditeurs."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from infrastructure.read_models._common import FacetOption, PaginatedResponse, YesNoCount

# Vocabulaire de tri de la liste des éditeurs : le champ, puis le sens.
PublisherSort = Literal[
    "name_asc",
    "name_desc",
    "serials_asc",
    "serials_desc",
    "publications_asc",
    "publications_desc",
]


@dataclass(frozen=True, slots=True)
class PublisherFilters:
    """Filtres que la liste des éditeurs et ses facettes honorent toutes deux.

    `publisher_types` et `countries` sont multi-valués. `has_publications` retient les éditeurs dont le décompte de publications du périmètre est non nul (`True`) ou nul (`False`).
    """

    search: str = ""
    publisher_types: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    has_publications: bool | None = None


class DoiPrefixInfo(BaseModel):
    """Préfixe DOI rattaché à un éditeur (`doi_prefixes`)."""

    prefix: str
    ra: str
    crossref_member_id: int | None = None


class PublisherListItem(BaseModel):
    """Ligne de la liste des éditeurs.

    `publication_count` compte les seules publications du périmètre, sommées sur les revues de l'éditeur.
    """

    id: int
    name: str
    openalex_id: str | None
    country: str | None
    publisher_type: str
    serial_count: int
    publication_count: int
    doi_prefixes: list[DoiPrefixInfo]


class Publisher(PublisherListItem):
    """Profil d'un éditeur (page publique `/publishers/[id]`)."""


class PublisherListResponse(PaginatedResponse):
    publishers: list[PublisherListItem]


class PublishersFacetsResponse(BaseModel):
    """Facettes dynamiques pour `/api/publishers`.

    Pour `publisher_types`, `label` reprend `PUBLISHER_TYPE_LABELS_FR` ; pour `countries` (code ISO observé en base), `label` est le nom du pays. `publications` compte les éditeurs avec et sans publication du périmètre. Chaque décompte écarte le filtre de sa dimension.
    """

    publisher_types: list[FacetOption]
    countries: list[FacetOption]
    publications: YesNoCount
