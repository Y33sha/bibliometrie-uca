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
