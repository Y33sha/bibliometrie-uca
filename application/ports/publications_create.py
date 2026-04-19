"""Port : SQL du script `create_publications`.

Implémenté par `infrastructure.db.queries.publications_create.PgPublicationsCreateQueries`.
"""

from typing import Any, Protocol


class PublicationsCreateQueries(Protocol):
    """Opérations SQL pour la création de publications depuis les source_publications."""

    def fetch_orphan_in_perimeter_source_publications(self, cur: Any) -> list[dict[str, Any]]: ...

    def link_source_publication_to_publication(
        self, cur: Any, source_publication_id: int, publication_id: int
    ) -> None: ...
