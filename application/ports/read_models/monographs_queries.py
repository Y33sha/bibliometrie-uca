"""Port : lectures sur les monographies (consommé par le router monographs).

Implémenté par `infrastructure.read_models.monographs.PgMonographQueries`.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel

from application.ports.read_models._common import (
    EntityFacetResponse,
    FacetOption,
    PaginatedResponse,
)

# Vocabulaire de tri de la liste des monographies : le champ, puis le sens.
MonographSort = Literal["title_asc", "title_desc", "year_asc", "year_desc", "pubs_asc", "pubs_desc"]

MONOGRAPH_KINDS = ("book", "proceedings")
"""Types de monographie : livre, volume d'actes."""

MonographEntityKind = Literal["publisher", "journal"]
"""Entités qui filtrent la liste des monographies : l'éditeur, la collection."""


@dataclass(frozen=True, slots=True)
class MonographFilters:
    """Filtres de la liste des monographies. `search` porte sur le titre, ou sur l'ISBN quand le terme en a la forme. `kinds` et `years` retiennent les types et les années listés ; vides, ils retiennent tout. `publisher_id` et `journal_id` restreignent à un éditeur et à une collection."""

    search: str = ""
    kinds: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    publisher_id: int | None = None
    journal_id: int | None = None


class MonographListItem(BaseModel):
    """Ligne de la liste des monographies. `pub_count` compte les publications qu'elle contient."""

    id: int
    title: str
    proceedings: bool
    year: int | None
    isbn: str | None
    eisbn: str | None
    publisher_id: int | None
    pub_name: str | None
    journal_id: int | None
    journal_title: str | None
    pub_count: int


class MonographListResponse(PaginatedResponse):
    monographs: list[MonographListItem]


class MonographsFacetsResponse(BaseModel):
    """Facettes de la liste des monographies. Chaque décompte écarte le filtre de sa dimension : il annonce le nombre de monographies atteignables si l'option était cochée."""

    kinds: list[FacetOption]
    years: list[FacetOption]


class MonographQueries(Protocol):
    """Opérations de lecture sur les monographies."""

    def list_monographs(
        self, *, filters: MonographFilters, sort: MonographSort, page: int, per_page: int
    ) -> MonographListResponse: ...

    def monographs_facets(self, *, filters: MonographFilters) -> MonographsFacetsResponse: ...

    def monographs_entity_facet(
        self, *, kind: MonographEntityKind, search: str, filters: MonographFilters
    ) -> EntityFacetResponse: ...

    def get_monograph(self, monograph_id: int) -> MonographListItem | None: ...
