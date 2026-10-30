"""Modèles de réponse : lectures sur les monographies."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from infrastructure.read_models._common import (
    FacetOption,
    PaginatedResponse,
)

# Vocabulaire de tri de la liste des monographies : le champ, puis le sens.
MonographSort = Literal[
    "title_asc", "title_desc", "year_asc", "year_desc", "publications_asc", "publications_desc"
]

MONOGRAPH_KINDS = ("book", "proceedings")
"""Types de monographie : livre, volume d'actes."""

MonographEntityKind = Literal["publisher", "serial"]
"""Entités qui filtrent la liste des monographies : l'éditeur, la collection."""


@dataclass(frozen=True, slots=True)
class MonographFilters:
    """Filtres de la liste des monographies."""

    search: str = ""
    """Terme cherché dans le titre, ou dans l'ISBN quand le terme a la forme d'un ISBN."""
    kinds: tuple[str, ...] = ()
    """Types retenus ; vide, tous les types."""
    years: tuple[int, ...] = ()
    """Années retenues ; vide, toutes les années."""
    publisher_id: int | None = None
    serial_id: int | None = None
    """Collection de la monographie."""


class MonographListItem(BaseModel):
    """Ligne de la liste des monographies."""

    id: int
    title: str
    proceedings: bool
    year: int | None
    isbn: str | None
    eisbn: str | None
    publisher_id: int | None
    publisher_name: str | None
    serial_id: int | None
    journal_title: str | None
    publication_count: int
    """Nombre de publications de la monographie."""


class MonographListResponse(PaginatedResponse):
    monographs: list[MonographListItem]


class MonographsFacetsResponse(BaseModel):
    """Facettes de la liste des monographies. Chaque décompte écarte le filtre de sa dimension : il donne le nombre de monographies retenues si l'option est cochée."""

    kinds: list[FacetOption]
    years: list[FacetOption]
