"""Port : lectures/écritures pour les scripts de fusion cross-source.

Implémenté par `infrastructure.db.queries.merge.PgMergeQueries`.
"""

from typing import Any, Protocol

from sqlalchemy import Connection


class MergeQueries(Protocol):
    """Opérations SQL pour les scripts de fusion par NNT / hal_id."""

    def find_nnt_duplicates(self, conn: Connection) -> list[dict[str, Any]]: ...

    def rank_publications_by_merge_priority(
        self, conn: Connection, publication_ids: list[int]
    ) -> list[dict[str, Any]]: ...

    def fetch_source_publications_with_hal_external_id(
        self, conn: Connection
    ) -> list[dict[str, Any]]: ...

    def fetch_hal_source_publications(self, conn: Connection) -> list[dict[str, Any]]: ...

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None: ...
