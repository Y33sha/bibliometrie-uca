"""Port : lectures sur les revues (consommé par le router journals).

Implémenté par `infrastructure.queries.journals.PgJournalQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4 — les DTOs vivent dans le port qui les définit (zone neutre, à côté des Protocols).
"""

from typing import Protocol

from pydantic import BaseModel


class JournalOut(BaseModel):
    """Représentation d'une revue dans la liste paginée `/api/journals`.

    `pub_name` est joint depuis `publishers`, `pub_count` est un agrégat
    sur `publications` ; ni l'un ni l'autre ne sont des colonnes natives
    de la table `journals`.
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


class JournalBasic(BaseModel):
    """GET /api/journals/{id} : id + title (recherche par id)."""

    id: int
    title: str


class JournalQueries(Protocol):
    """Opérations de lecture sur les revues."""

    def list_journals(
        self,
        *,
        search: str | None,
        publisher_id: int | None,
        sort: str,
        page: int,
        per_page: int,
    ) -> JournalListResponse: ...

    def get_journal(self, journal_id: int) -> JournalBasic | None: ...

    def existing_journal_ids(self, journal_ids: tuple[int, ...]) -> set[int]: ...
