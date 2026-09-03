"""Query services de lecture autour des publications (router publications).

Le package est organisé par thème :
- `list` : `list_publications`, `export_publications_csv`, `export_theses_csv`
- `facets` : `publications_facets`
- `detail` : `get_publication_detail`

Les adapters d'écriture pipeline (`pipeline.publications_reconciliation`, `pipeline.metadata_correction`) vivent côté `infrastructure/pipeline/`.

`PgPublicationsQueries` agrège les 5 fonctions de lecture sous le port `application.ports.read_models.publications_queries.PublicationsQueries`. Les fonctions libres retournent des dicts (réutilisables hors API) ; la conversion vers les DTOs Pydantic est faite ici à la sortie de l'adapter.
"""

# Annotations différées : sinon `list[int]` est résolu comme le sous-module `.list` (le `from .list import …` ci-dessous l'attache au package, et le namespace global du __init__ shadow le builtin `list`).
from __future__ import annotations

from collections.abc import Callable, Iterator

from sqlalchemy import Connection

from application.ports.read_models._common import (
    EntityFacetResponse,
    EntityKind,
)
from application.ports.read_models.publications_queries import (
    PublicationDetailResponse,
    PublicationFilters,
    PublicationListResponse,
    PublicationsFacetsResponse,
    PublicationsQueries,
)
from infrastructure.read_models.perimeters import get_persons_structure_ids_list
from infrastructure.read_models.publications.detail import (
    get_publication_detail as _get_publication_detail,
)
from infrastructure.read_models.publications.facets import (
    publications_entity_facet as _publications_entity_facet,
    publications_facets as _publications_facets,
)
from infrastructure.read_models.publications.list import (
    export_publications_csv as _export_publications_csv,
    export_theses_csv as _export_theses_csv,
    list_publications as _list_publications,
)


class PgPublicationsQueries(PublicationsQueries):
    """Adapter SA pour `application.ports.read_models.publications_queries.PublicationsQueries`.

    Le filtre `has_apc` classe un paiement d'APC en « interne » quand sa structure de budget appartient au périmètre `persons`. L'adapter résout ce périmètre là où il sert : ses appelants n'ont pas à le connaître pour lister des publications.
    """

    def __init__(self, conn: Connection, *, open_connection: Callable[[], Connection]) -> None:
        """`open_connection` ouvre les connexions supplémentaires dont le calcul parallèle des facettes se sert. Elle est fournie par la composition root, qui y met les caractéristiques de la requête en cours ; l'adapter reçoit ses connexions, il n'en ouvre pas de son propre chef."""
        self._conn = conn
        self._open_connection = open_connection

    def list_publications(
        self,
        *,
        filters: PublicationFilters,
        page: int,
        per_page: int,
        sort: str,
    ) -> PublicationListResponse:
        return _list_publications(
            self._conn,
            filters=filters,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            page=page,
            per_page=per_page,
            sort=sort,
        )

    def publications_facets(self, *, filters: PublicationFilters) -> PublicationsFacetsResponse:
        return _publications_facets(
            self._conn,
            filters=filters,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            open_connection=self._open_connection,
        )

    def publications_entity_facet(
        self,
        *,
        kind: EntityKind,
        search: str,
        filters: PublicationFilters,
    ) -> EntityFacetResponse:
        return EntityFacetResponse(
            entities=_publications_entity_facet(
                self._conn,
                kind=kind,
                search=search,
                filters=filters,
                perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            )
        )

    def export_publications_csv(
        self,
        *,
        filters: PublicationFilters,
        sort: str,
        columns: list[str],
    ) -> Iterator[str]:
        return _export_publications_csv(
            self._conn,
            filters=filters,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            sort=sort,
            columns=columns,
        )

    def export_theses_csv(self, *, filters: PublicationFilters, sort: str) -> Iterator[str]:
        return _export_theses_csv(
            self._conn,
            filters=filters,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            sort=sort,
        )

    def get_publication_detail(self, pub_id: int) -> PublicationDetailResponse | None:
        return _get_publication_detail(self._conn, pub_id)


__all__ = ["PgPublicationsQueries"]
