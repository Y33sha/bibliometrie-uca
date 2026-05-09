"""Port : lectures pour /api/admin/duplicates/*.

Deux variantes (chantier sync-async-deduplication, option D) :
- `AsyncPublicationDuplicatesQueries` : routers async.
- `PublicationDuplicatesQueries` : routers sync.

Implémentés respectivement par `PgAsyncPublicationDuplicatesQueries`
et `PgPublicationDuplicatesQueries` dans
`infrastructure.db.queries.publication_duplicates`.
"""

from typing import Any, Protocol


class AsyncPublicationDuplicatesQueries(Protocol):
    """Lectures async pour le dédoublonnage des publications."""

    async def next_pub_duplicate(self, *, min_title_len: int, offset: int) -> dict[str, Any]: ...

    async def get_publications_basic(self, pub_ids: list[int]) -> dict[int, Any]: ...


class PublicationDuplicatesQueries(Protocol):
    """Variante sync d'`AsyncPublicationDuplicatesQueries`."""

    def next_pub_duplicate(self, *, min_title_len: int, offset: int) -> dict[str, Any]: ...

    def get_publications_basic(self, pub_ids: list[int]) -> dict[int, Any]: ...
