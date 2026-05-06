"""Port : lectures stats (consommé par le router stats).

Implémenté par
`infrastructure.db.queries.stats.PgAsyncStatsQueries`.
"""

from typing import Any, Protocol


class AsyncStatsQueries(Protocol):
    """Lectures pour /api/stats/*."""

    async def publisher_stats(
        self,
        *,
        root_structure_id: int,
        lab_ids: list[int],
        years: list[int],
        oa_status: str,
        has_apc: str,
        search: str,
        page: int,
        per_page: int,
        sort: str,
    ) -> dict[str, Any]: ...

    async def journal_stats(
        self,
        *,
        root_structure_id: int,
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        oa_status: str,
        has_apc: str,
        search: str,
        page: int,
        per_page: int,
        sort: str,
    ) -> dict[str, Any]: ...

    async def stats_labs(
        self,
        *,
        root_structure_id: int,
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        journal_id: int | None,
        oa_status: str,
        has_apc: str,
        page: int,
        per_page: int,
        sort: str,
    ) -> dict[str, Any]: ...

    async def stats_by_year(
        self,
        *,
        root_structure_id: int,
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        journal_id: int | None,
        oa_status: str,
        has_apc: str,
    ) -> list[dict[str, Any]]: ...

    async def stats_summary(
        self,
        *,
        root_structure_id: int,
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        journal_id: int | None,
        oa_status: str,
        has_apc: str,
    ) -> dict[str, Any]: ...

    async def available_years(self) -> list[int]: ...

    async def stats_facets(
        self,
        *,
        root_structure_id: int,
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        journal_id: int | None,
        oa_status: str,
        has_apc: str,
    ) -> dict[str, list[dict[str, Any]]]: ...
