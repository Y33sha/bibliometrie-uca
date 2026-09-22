"""Port : lectures sur les monographies (consommé par le router monographs).

Implémenté par `infrastructure.read_models.monographs.PgMonographQueries`.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel

from application.ports.read_models._common import PaginatedResponse

# Vocabulaire de tri de la liste des monographies : le champ, puis le sens.
MonographSort = Literal["title_asc", "title_desc", "year_asc", "year_desc", "pubs_asc", "pubs_desc"]

MonographKind = Literal["", "book", "proceedings"]
"""Livre, volume d'actes, ou les deux (valeur vide)."""


@dataclass(frozen=True, slots=True)
class MonographFilters:
    """Filtres de la liste des monographies. `search` porte sur le titre, ou sur l'ISBN quand le terme en a la forme."""

    search: str = ""
    kind: MonographKind = ""


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


class MonographQueries(Protocol):
    """Opérations de lecture sur les monographies."""

    def list_monographs(
        self, *, filters: MonographFilters, sort: MonographSort, page: int, per_page: int
    ) -> MonographListResponse: ...

    def get_monograph(self, monograph_id: int) -> MonographListItem | None: ...
