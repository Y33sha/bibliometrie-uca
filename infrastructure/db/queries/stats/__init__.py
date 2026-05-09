"""Query services pour /api/stats/* (router stats).

Le package est organisé par thème d'agrégat :
- `publishers` : `publisher_stats` (+ `_sync`)
- `journals` : `journal_stats` (+ `_sync`)
- `labs` : `stats_labs` (+ `_sync`)
- `summary` : `stats_by_year`, `stats_summary`, `available_years`, `stats_facets` (+ `_sync`)
- `_shared` : filtre APC + pagination partagés par tous les agrégats.

`PgAsyncStatsQueries` / `PgStatsQueries` agrègent les 7 fonctions sous
les ports `application.ports.stats_queries.AsyncStatsQueries` /
`StatsQueries`.
"""

from typing import Any

from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.queries.stats.journals import (
    journal_stats as _journal_stats,
)
from infrastructure.db.queries.stats.journals import (
    journal_stats_sync as _journal_stats_sync,
)
from infrastructure.db.queries.stats.labs import (
    stats_labs as _stats_labs,
)
from infrastructure.db.queries.stats.labs import (
    stats_labs_sync as _stats_labs_sync,
)
from infrastructure.db.queries.stats.publishers import (
    publisher_stats as _publisher_stats,
)
from infrastructure.db.queries.stats.publishers import (
    publisher_stats_sync as _publisher_stats_sync,
)
from infrastructure.db.queries.stats.summary import (
    available_years as _available_years,
)
from infrastructure.db.queries.stats.summary import (
    available_years_sync as _available_years_sync,
)
from infrastructure.db.queries.stats.summary import (
    stats_by_year as _stats_by_year,
)
from infrastructure.db.queries.stats.summary import (
    stats_by_year_sync as _stats_by_year_sync,
)
from infrastructure.db.queries.stats.summary import (
    stats_facets as _stats_facets,
)
from infrastructure.db.queries.stats.summary import (
    stats_facets_sync as _stats_facets_sync,
)
from infrastructure.db.queries.stats.summary import (
    stats_summary as _stats_summary,
)
from infrastructure.db.queries.stats.summary import (
    stats_summary_sync as _stats_summary_sync,
)


class PgAsyncStatsQueries:
    """Adapter SA pour `application.ports.stats_queries.AsyncStatsQueries`."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def publisher_stats(self, **kwargs: Any) -> dict[str, Any]:
        return await _publisher_stats(self._conn, **kwargs)

    async def journal_stats(self, **kwargs: Any) -> dict[str, Any]:
        return await _journal_stats(self._conn, **kwargs)

    async def stats_labs(self, **kwargs: Any) -> dict[str, Any]:
        return await _stats_labs(self._conn, **kwargs)

    async def stats_by_year(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await _stats_by_year(self._conn, **kwargs)

    async def stats_summary(self, **kwargs: Any) -> dict[str, Any]:
        return await _stats_summary(self._conn, **kwargs)

    async def available_years(self) -> list[int]:
        return await _available_years(self._conn)

    async def stats_facets(self, **kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        return await _stats_facets(self._conn, **kwargs)


class PgStatsQueries:
    """Variante sync de `PgAsyncStatsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def publisher_stats(self, **kwargs: Any) -> dict[str, Any]:
        return _publisher_stats_sync(self._conn, **kwargs)

    def journal_stats(self, **kwargs: Any) -> dict[str, Any]:
        return _journal_stats_sync(self._conn, **kwargs)

    def stats_labs(self, **kwargs: Any) -> dict[str, Any]:
        return _stats_labs_sync(self._conn, **kwargs)

    def stats_by_year(self, **kwargs: Any) -> list[dict[str, Any]]:
        return _stats_by_year_sync(self._conn, **kwargs)

    def stats_summary(self, **kwargs: Any) -> dict[str, Any]:
        return _stats_summary_sync(self._conn, **kwargs)

    def available_years(self) -> list[int]:
        return _available_years_sync(self._conn)

    def stats_facets(self, **kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        return _stats_facets_sync(self._conn, **kwargs)


__all__ = ["PgAsyncStatsQueries", "PgStatsQueries"]
