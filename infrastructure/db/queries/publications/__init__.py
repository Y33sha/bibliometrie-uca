"""Query services autour des publications.

Le package est organisé par thème :
- `list` : `list_publications`, `export_publications_csv`, `export_theses_csv`
- `facets` : `publications_facets`
- `detail` : `all_years`, `get_publication_detail`
- `match_or_create` : `PgPublicationsMatchOrCreateQueries` (adapter du port
  `application.ports.pipeline.publications_match_or_create`, sync, consommé par le pipeline)

`PgPublicationsQueries` agrège les 6 fonctions de lecture sous le port
`application.ports.publications_queries.PublicationsQueries`. Les
dataclasses `FacetFilters` / `ListFilters` vivent côté port (source de
vérité), ici on type `filters: Any`.
"""

# Annotations différées : sinon `list[int]` est résolu comme le sous-module
# `.list` (le `from .list import …` ci-dessous l'attache au package, et le
# namespace global du __init__ shadow le builtin `list`).
from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

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
from infrastructure.db.queries.publications.match_or_create import (
    PgPublicationsMatchOrCreateQueries,
)


class PgPublicationsQueries:
    """Adapter SA pour `application.ports.publications_queries.PublicationsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_publications(self, **kwargs: Any) -> dict[str, Any]:
        return _list_publications(self._conn, **kwargs)

    def publications_facets(self, **kwargs: Any) -> dict[str, Any]:
        return _publications_facets(self._conn, **kwargs)

    def export_publications_csv(self, **kwargs: Any) -> str:
        return _export_publications_csv(self._conn, **kwargs)

    def export_theses_csv(self, **kwargs: Any) -> str:
        return _export_theses_csv(self._conn, **kwargs)

    def all_years(self) -> list[int]:
        return _all_years(self._conn)

    def get_publication_detail(self, pub_id: int) -> dict[str, Any] | None:
        return _get_publication_detail(self._conn, pub_id)


__all__ = ["PgPublicationsMatchOrCreateQueries", "PgPublicationsQueries"]
