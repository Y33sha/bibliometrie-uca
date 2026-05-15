"""Port : lectures pour /api/admin/duplicates/*.

Implémenté par
`infrastructure.queries.publication_duplicates.PgPublicationDuplicatesQueries`.
"""

from typing import Any, Protocol


class PublicationDuplicatesQueries(Protocol):
    """Lectures pour le dédoublonnage des publications."""

    def next_pub_duplicate(self, *, min_title_len: int, offset: int) -> dict[str, Any]: ...

    def get_publications_basic(self, pub_ids: list[int]) -> dict[int, Any]: ...
