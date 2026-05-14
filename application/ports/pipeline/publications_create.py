"""Port : SQL du script `create_publications`.

Implémenté par `infrastructure.db.queries.publications.create.PgPublicationsCreateQueries`.
"""

from typing import Any, Protocol

from sqlalchemy import Connection


class PublicationsCreateQueries(Protocol):
    """Opérations SQL pour la création de publications depuis les source_publications."""

    def fetch_orphan_in_perimeter_source_publications(
        self, conn: Connection
    ) -> list[dict[str, Any]]: ...

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
