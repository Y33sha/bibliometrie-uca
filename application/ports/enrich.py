"""Port : lectures pour les scripts d'enrichissement.

Implémenté par `infrastructure.db.queries.enrich.PgEnrichQueries`.
"""

from typing import Any, Protocol


class EnrichQueries(Protocol):
    """Opérations SQL pour les scripts d'enrichissement pipeline."""

    def fetch_publications_with_doi(
        self, conn: Any, *, limit: int | None = None
    ) -> list[tuple[int, str, str | None]]: ...

    def fetch_journals_needing_apc(
        self, conn: Any, *, limit: int | None = None
    ) -> list[tuple[int, str]]: ...
