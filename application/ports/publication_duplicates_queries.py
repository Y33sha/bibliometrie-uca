"""Port : lectures pour /api/admin/duplicates/*.

Implémenté par
`infrastructure.db.queries.publication_duplicates.PgAsyncPublicationDuplicatesQueries`.
"""

from typing import Any, Protocol


class AsyncPublicationDuplicatesQueries(Protocol):
    """Lectures async pour le dédoublonnage des publications."""

    async def next_pub_duplicate(self, *, min_title_len: int, offset: int) -> dict[str, Any]: ...

    async def get_publications_basic(self, pub_ids: list[int]) -> dict[int, Any]: ...
