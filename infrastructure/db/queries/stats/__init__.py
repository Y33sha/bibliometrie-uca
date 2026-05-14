"""Query services pour /api/stats/* (router stats).

Le package est organisé par thème d'agrégat :
- `publishers` : `publisher_stats`
- `journals` : `journal_stats`
- `labs` : `stats_labs`
- `summary` : `stats_by_year`, `stats_summary`, `available_years`, `stats_facets`
- `_shared` : filtre APC + pagination partagés par tous les agrégats.

`PgStatsQueries` agrège les 7 fonctions sous le port
`application.ports.stats_queries.StatsQueries`.
"""

from typing import Any

from sqlalchemy import Connection

from application.ports.api.stats_queries import StatsQueries
from infrastructure.db.queries.stats.journals import journal_stats as _journal_stats
from infrastructure.db.queries.stats.labs import stats_labs as _stats_labs
from infrastructure.db.queries.stats.publishers import publisher_stats as _publisher_stats
from infrastructure.db.queries.stats.summary import (
    available_years as _available_years,
)
from infrastructure.db.queries.stats.summary import (
    stats_by_year as _stats_by_year,
)
from infrastructure.db.queries.stats.summary import (
    stats_facets as _stats_facets,
)
from infrastructure.db.queries.stats.summary import (
    stats_summary as _stats_summary,
)


class PgStatsQueries(StatsQueries):
    """Adapter SA pour `application.ports.stats_queries.StatsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

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
    ) -> dict[str, Any]:
        return _publisher_stats(
            self._conn,
            root_structure_id=root_structure_id,
            lab_ids=lab_ids,
            years=years,
            oa_status=oa_status,
            has_apc=has_apc,
            search=search,
            page=page,
            per_page=per_page,
            sort=sort,
        )

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
    ) -> dict[str, Any]:
        return _journal_stats(
            self._conn,
            root_structure_id=root_structure_id,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            oa_status=oa_status,
            has_apc=has_apc,
            search=search,
            page=page,
            per_page=per_page,
            sort=sort,
        )

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
    ) -> dict[str, Any]:
        return _stats_labs(
            self._conn,
            root_structure_id=root_structure_id,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
            page=page,
            per_page=per_page,
            sort=sort,
        )

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
    ) -> list[dict[str, Any]]:
        return _stats_by_year(
            self._conn,
            root_structure_id=root_structure_id,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
        )

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
    ) -> dict[str, Any]:
        return _stats_summary(
            self._conn,
            root_structure_id=root_structure_id,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
        )

    def available_years(self) -> list[int]:
        return _available_years(self._conn)

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
    ) -> dict[str, list[dict[str, Any]]]:
        return _stats_facets(
            self._conn,
            root_structure_id=root_structure_id,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
        )


__all__ = ["PgStatsQueries"]
