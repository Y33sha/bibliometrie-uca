"""Query services pour /api/stats/* (router stats).

Le package est organisé par thème d'agrégat :
- `publishers` : `publisher_stats`
- `journals` : `journal_stats`
- `labs` : `stats_labs`
- `summary` : `stats_by_year`, `stats_summary`, `available_years`, `stats_facets`
- `_shared` : filtre APC + pagination partagés par tous les agrégats.

`PgAsyncStatsQueries` agrège les 7 fonctions sous le port
`application.ports.stats_queries.AsyncStatsQueries`.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

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


__all__ = ["PgAsyncStatsQueries"]
