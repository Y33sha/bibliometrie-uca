"""Modèles de réponse : lectures sur les éditeurs."""

from dataclasses import dataclass, field
from typing import Literal

from application.ports.model import Model
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
    """Filtres communs à la liste des éditeurs et à ses facettes. `publisher_types` et `countries` sont multi-valués."""

    search: str = ""
    publisher_types: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    has_publications: bool | None = None
    """Retient les éditeurs à décompte de publications du périmètre non nul (`True`) ou nul (`False`)."""


class DoiPrefixInfo(Model):
    """Préfixe DOI rattaché à un éditeur (`doi_prefixes`)."""

    prefix: str
    ra: str
    crossref_member_id: int | None = None


class PublisherListItem(Model):
    """Ligne de la liste des éditeurs."""

    id: int
    name: str
    openalex_id: str | None
    country: str | None
    publisher_type: str
    serial_count: int
    publication_count: int
    """Publications du périmètre seulement, sommées sur les revues de l'éditeur."""
    doi_prefixes: list[DoiPrefixInfo]


class Publisher(PublisherListItem):
    """Profil d'un éditeur (page publique `/publishers/[id]`)."""


class PublisherListResponse(PaginatedResponse):
    publishers: list[PublisherListItem]


class PublishersFacetsResponse(Model):
    """Facettes dynamiques de `/api/publishers`. Chaque décompte écarte le filtre de sa dimension."""

    publisher_types: list[FacetOption]
    """Libellés tirés de `PUBLISHER_TYPE_LABELS_FR`."""
    countries: list[FacetOption]
    """Code ISO observé en base, avec le nom du pays en libellé."""
    publications: YesNoCount
    """Éditeurs avec et sans publication du périmètre."""
