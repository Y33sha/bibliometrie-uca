"""Port : lectures pour /api/admin/duplicates/* (doublons publications).

Implémenté par `infrastructure.queries.api.publication_duplicates.PgPublicationDuplicatesQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4.
"""

from typing import Protocol

from pydantic import BaseModel


class PubDedupJournal(BaseModel):
    id: int
    title: str | None
    issn: str | None
    eissn: str | None


class PubDedupSource(BaseModel):
    source: str
    source_id: str


class PubDedupAuthor(BaseModel):
    author_position: int | None
    in_perimeter: bool
    person_id: int | None
    last_name: str | None
    first_name: str | None
    full_name: str | None


class PubDedupDetail(BaseModel):
    """Détail d'une publication pour la page de déduplication."""

    id: int
    title: str
    title_normalized: str
    doi: str | None
    pub_year: int | None
    doc_type: str
    container_title: str | None
    oa_status: str
    language: str | None
    journal: PubDedupJournal | None
    sources: list[PubDedupSource]
    authors: list[PubDedupAuthor]


class PubDuplicatePair(BaseModel):
    pub_a: PubDedupDetail
    pub_b: PubDedupDetail


class PubDuplicateNextResponse(BaseModel):
    total: int
    offset: int
    pair: PubDuplicatePair | None


class PublicationDuplicatesQueries(Protocol):
    """Lectures pour le dédoublonnage des publications."""

    def next_pub_duplicate(
        self, *, min_title_len: int, offset: int
    ) -> PubDuplicateNextResponse: ...

    def existing_publication_ids(self, pub_ids: tuple[int, ...]) -> set[int]: ...
