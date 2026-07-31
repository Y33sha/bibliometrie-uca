"""Port : lectures sur les signatures (consommé par le router authorships).

Implémenté par `infrastructure.read_models.authorships.PgAuthorshipsQueries`. La file des signatures orphelines lit `source_authorships` un cran sous les signatures consolidées : elle appartient donc aux authorships, non aux personnes qu'elle sert à rattacher.
"""

from typing import Protocol

from pydantic import BaseModel

from application.ports.read_models._common import PaginatedResponse


class OrphanCountResponse(BaseModel):
    total: int


class OrphanAuthorshipOut(BaseModel):
    source: str
    source_authorship_id: int
    full_name: str
    last_name: str
    first_name: str
    publication_id: int
    pub_title: str
    pub_year: int | None


class OrphanAuthorshipsResponse(PaginatedResponse):
    authorships: list[OrphanAuthorshipOut]


class AuthorshipsQueries(Protocol):
    """Lectures sync pour `/api/authorships/*`."""

    def orphan_authorships_count(self) -> OrphanCountResponse:
        """Nombre de signatures du périmètre qu'aucune personne ne porte."""
        ...

    def list_orphan_authorships(
        self, *, search: str, page: int, per_page: int
    ) -> OrphanAuthorshipsResponse:
        """Liste paginée des signatures orphelines, avec la publication qu'elles signent."""
        ...
