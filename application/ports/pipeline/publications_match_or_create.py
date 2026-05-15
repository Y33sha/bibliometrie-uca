"""Port : SQL de la phase publications (`match_or_create_publications`).

Implémenté par `infrastructure.db.queries.publications.match_or_create.PgPublicationsMatchOrCreateQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PublicationsMatchOrCreateQueries(Protocol):
    """Opérations SQL pour le rattachement (match ou création) des `source_publications` aux `publications` canoniques."""

    def fetch_orphan_in_perimeter_source_publications(
        self, conn: Connection
    ) -> list[dict[str, object]]: ...

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None: ...

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None: ...

    def fetch_thesis_primary_author_from_source_publication(
        self, conn: Connection, source_publication_id: int
    ) -> tuple[str, str] | None: ...

    def fetch_stale_publication_ids(self, conn: Connection) -> list[int]: ...
