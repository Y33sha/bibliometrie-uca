"""Query services de lecture autour des publications (router publications).

Le package est organisé par thème :
- `list` : `list_publications`, `export_publications_csv`, `export_theses_csv`
- `facets` : `publications_facets`
- `detail` : `get_publication_detail`

Les adapters d'écriture pipeline (`pipeline.publications_reconciliation`,
`pipeline.metadata_correction`) vivent côté `infrastructure/queries/pipeline/`.

`PgPublicationsQueries` agrège les 5 fonctions de lecture sous le port
`application.ports.api.publications_queries.PublicationsQueries`. Les fonctions
libres retournent des dicts (réutilisables hors API) ; la conversion vers les
DTOs Pydantic est faite ici à la sortie de l'adapter.
"""

# Annotations différées : sinon `list[int]` est résolu comme le sous-module
# `.list` (le `from .list import …` ci-dessous l'attache au package, et le
# namespace global du __init__ shadow le builtin `list`).
from __future__ import annotations

from sqlalchemy import Connection

from application.ports.api.publications_queries import (
    FacetFilters,
    ListFilters,
    PublicationDetailResponse,
    PublicationListResponse,
    PublicationsFacetsResponse,
    PublicationsQueries,
)
from infrastructure.queries.api.publications.detail import (
    get_publication_detail as _get_publication_detail,
)
from infrastructure.queries.api.publications.facets import (
    publications_facets as _publications_facets,
)
from infrastructure.queries.api.publications.list import (
    export_publications_csv as _export_publications_csv,
)
from infrastructure.queries.api.publications.list import (
    export_theses_csv as _export_theses_csv,
)
from infrastructure.queries.api.publications.list import (
    list_publications as _list_publications,
)


class PgPublicationsQueries(PublicationsQueries):
    """Adapter SA pour `application.ports.api.publications_queries.PublicationsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_publications(
        self,
        *,
        filters: ListFilters,
        apc_structure_ids: list[int],
        page: int,
        per_page: int,
        sort: str,
    ) -> PublicationListResponse:
        data = _list_publications(
            self._conn,
            filters=filters,
            apc_structure_ids=apc_structure_ids,
            page=page,
            per_page=per_page,
            sort=sort,
        )
        return PublicationListResponse.model_validate(data)

    def publications_facets(
        self, *, filters: FacetFilters, apc_structure_ids: list[int]
    ) -> PublicationsFacetsResponse:
        data = _publications_facets(
            self._conn, filters=filters, apc_structure_ids=apc_structure_ids
        )
        return PublicationsFacetsResponse.model_validate(data)

    def export_publications_csv(
        self,
        *,
        filters: ListFilters,
        apc_structure_ids: list[int],
        sort: str,
        columns: list[str],
    ) -> str:
        return _export_publications_csv(
            self._conn,
            filters=filters,
            apc_structure_ids=apc_structure_ids,
            sort=sort,
            columns=columns,
        )

    def export_theses_csv(
        self, *, filters: ListFilters, apc_structure_ids: list[int], sort: str
    ) -> str:
        return _export_theses_csv(
            self._conn, filters=filters, apc_structure_ids=apc_structure_ids, sort=sort
        )

    def get_publication_detail(self, pub_id: int) -> PublicationDetailResponse | None:
        data = _get_publication_detail(self._conn, pub_id)
        if data is None:
            return None
        return PublicationDetailResponse.model_validate(data)


__all__ = ["PgPublicationsQueries"]
