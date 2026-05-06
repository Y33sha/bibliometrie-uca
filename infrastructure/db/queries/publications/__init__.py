"""Query services autour des publications.

Le package est organisé par thème :
- `list` : `list_publications`, `export_publications_csv`, `export_theses_csv`
- `facets` : `publications_facets`
- `detail` : `all_years`, `get_publication_detail`
- `create` : `PgPublicationsCreateQueries` (adapter du port
  `application.ports.publications_create`)

`PgAsyncPublicationsQueries` agrège les 6 fonctions de lecture sous le
port `application.ports.publications_queries.AsyncPublicationsQueries`.
Les dataclasses `FacetFilters` / `ListFilters` vivent côté port (source
de vérité), ici on type `filters: Any`.
"""

# Annotations différées : sinon `list[int]` est résolu comme le sous-module
# `.list` (le `from .list import …` ci-dessous l'attache au package, et le
# namespace global du __init__ shadow le builtin `list`).
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.queries.publications.create import PgPublicationsCreateQueries
from infrastructure.db.queries.publications.detail import (
    all_years as _all_years,
)
from infrastructure.db.queries.publications.detail import (
    get_publication_detail as _get_publication_detail,
)
from infrastructure.db.queries.publications.facets import (
    publications_facets as _publications_facets,
)
from infrastructure.db.queries.publications.list import (
    export_publications_csv as _export_publications_csv,
)
from infrastructure.db.queries.publications.list import (
    export_theses_csv as _export_theses_csv,
)
from infrastructure.db.queries.publications.list import (
    list_publications as _list_publications,
)


class PgAsyncPublicationsQueries:
    """Adapter SA pour `application.ports.publications_queries.AsyncPublicationsQueries`."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_publications(self, **kwargs: Any) -> dict[str, Any]:
        return await _list_publications(self._conn, **kwargs)

    async def publications_facets(self, **kwargs: Any) -> dict[str, Any]:
        return await _publications_facets(self._conn, **kwargs)

    async def export_publications_csv(self, **kwargs: Any) -> str:
        return await _export_publications_csv(self._conn, **kwargs)

    async def export_theses_csv(self, **kwargs: Any) -> str:
        return await _export_theses_csv(self._conn, **kwargs)

    async def all_years(self) -> list[int]:
        return await _all_years(self._conn)

    async def get_publication_detail(self, pub_id: int) -> dict[str, Any] | None:
        return await _get_publication_detail(self._conn, pub_id)


__all__ = ["PgAsyncPublicationsQueries", "PgPublicationsCreateQueries"]
