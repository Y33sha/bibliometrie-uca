"""Modèles Pydantic pour les éditeurs (publishers)."""

from pydantic import BaseModel


class PublisherUpdate(BaseModel):
    name: str | None = None
    country: str | None = None
    doi_prefix: str | None = None
    is_predatory: bool | None = None
    notes: str | None = None


class PublisherListItem(BaseModel):
    id: int
    name: str
    openalex_id: str | None
    country: str | None
    doi_prefix: str | None
    is_predatory: bool
    journal_count: int
    pub_count: int


class PublisherListResponse(BaseModel):
    total: int
    page: int
    pages: int
    publishers: list[PublisherListItem]


class PublisherBasic(BaseModel):
    """GET /api/publishers/{id} : juste id + name (recherche par id)."""

    id: int
    name: str
