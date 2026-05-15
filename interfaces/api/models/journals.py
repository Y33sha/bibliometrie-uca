"""Modèles Pydantic pour les revues (journals)."""

from pydantic import BaseModel


class JournalUpdate(BaseModel):
    title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    doi_prefix: str | None = None
    oa_model: str | None = None
    journal_type: str | None = None
    is_academic: bool | None = None
    is_predatory: bool | None = None
    is_in_doaj: bool | None = None
    apc_amount: float | None = None
    notes: str | None = None


class JournalOut(BaseModel):
    """Représentation d'une revue dans les réponses de /api/journals.

    Source : SELECT dans list_journals (router journals). Les champs
    reflètent les colonnes retournées — pub_name (nom éditeur joint)
    et pub_count (agrégat) ne sont pas des colonnes de la table
    journals mais sont exposés aux clients.
    """

    id: int
    title: str
    issn: str | None
    eissn: str | None
    issnl: str | None
    publisher_id: int | None
    pub_name: str | None
    openalex_id: str | None
    is_in_doaj: bool
    is_predatory: bool
    apc_amount: float | None
    apc_currency: str | None
    oa_model: str | None
    journal_type: str | None
    is_academic: bool | None
    doi_prefix: str | None
    notes: str | None
    pub_count: int


class JournalListResponse(BaseModel):
    total: int
    page: int
    pages: int
    journals: list[JournalOut]
