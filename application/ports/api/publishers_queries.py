"""Port : lectures sur les éditeurs (consommé par le router publishers).

Implémenté par `infrastructure.queries.publishers.PgPublisherQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4 — les DTOs vivent dans le port qui les définit (zone neutre, à côté des Protocols).
"""

from typing import Protocol

from pydantic import BaseModel


class DoiPrefixInfo(BaseModel):
    """Préfixe DOI rattaché à un éditeur (lecture seule, vient de la table `doi_prefixes`)."""

    prefix: str
    ra: str
    crossref_member_id: int | None = None


class PublisherListItem(BaseModel):
    id: int
    name: str
    openalex_id: str | None
    country: str | None
    doi_prefixes: list[DoiPrefixInfo]
    is_predatory: bool
    publisher_type: str
    journal_count: int
    pub_count: int


class PublisherListResponse(BaseModel):
    total: int
    page: int
    pages: int
    publishers: list[PublisherListItem]


class PublisherBasic(BaseModel):
    """GET /api/publishers/{id} : id + name (recherche par id)."""

    id: int
    name: str


class PublisherQueries(Protocol):
    """Opérations de lecture sur les éditeurs."""

    def list_publishers(
        self, *, search: str | None, sort: str, page: int, per_page: int
    ) -> PublisherListResponse: ...

    def get_publisher(self, publisher_id: int) -> PublisherBasic | None: ...

    def existing_publisher_ids(self, publisher_ids: tuple[int, ...]) -> set[int]: ...
