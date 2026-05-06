"""Port : lectures sur les éditeurs (consommé par le router publishers).

Implémenté par `infrastructure.db.queries.publishers.PgAsyncPublisherQueries`.
"""

from typing import Any, Protocol


class AsyncPublisherQueries(Protocol):
    """Opérations de lecture sur les éditeurs."""

    async def list_publishers(
        self, *, search: str | None, sort: str, page: int, per_page: int
    ) -> dict[str, Any]: ...

    async def get_publisher(self, publisher_id: int) -> dict[str, Any] | None: ...

    async def existing_publisher_ids(self, publisher_ids: tuple[int, ...]) -> set[int]: ...
