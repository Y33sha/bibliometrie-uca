"""Port : lectures stats (consommé par le router stats).

Implémenté par `infrastructure.db.queries.stats.PgStatsQueries`.
"""

from typing import Any, Protocol


class StatsQueries(Protocol):
    """Lectures pour /api/stats/*."""

    def publisher_stats(
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

    def journal_stats(
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

    def stats_labs(
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

    def stats_by_year(
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

    def stats_summary(
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

    def available_years(self) -> list[int]: ...

    def stats_facets(
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
