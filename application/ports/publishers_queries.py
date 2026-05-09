"""Port : lectures sur les éditeurs (consommé par le router publishers).

Deux variantes (chantier sync-async-deduplication, option D) :
- `AsyncPublisherQueries` : routers async.
- `PublisherQueries` : routers sync.

Implémentés respectivement par `PgAsyncPublisherQueries` et
`PgPublisherQueries` dans `infrastructure.db.queries.publishers`.
"""

from typing import Any, Protocol


class AsyncPublisherQueries(Protocol):
    """Opérations de lecture async sur les éditeurs."""

    async def list_publishers(
        self, *, search: str | None, sort: str, page: int, per_page: int
    ) -> dict[str, Any]: ...

    async def get_publisher(self, publisher_id: int) -> dict[str, Any] | None: ...

    async def existing_publisher_ids(self, publisher_ids: tuple[int, ...]) -> set[int]: ...


class PublisherQueries(Protocol):
    """Variante sync d'`AsyncPublisherQueries`."""

    def list_publishers(
        self, *, search: str | None, sort: str, page: int, per_page: int
    ) -> dict[str, Any]: ...

    def get_publisher(self, publisher_id: int) -> dict[str, Any] | None: ...

    def existing_publisher_ids(self, publisher_ids: tuple[int, ...]) -> set[int]: ...
