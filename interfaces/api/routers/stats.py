"""Router des agrégats des tableaux de bord, servis par `StatsQueries`. Sert `/api/stats/*`."""

from fastapi import APIRouter, Depends, Query

from infrastructure.read_models._common import EntityFacetResponse, EntityKind
from infrastructure.read_models.stats.models import (
    CollaborationsResponse,
    PivotResponse,
    PivotSchemaResponse,
    StatsFacetsResponse,
)
from infrastructure.read_models.stats.queries import StatsQueries
from interfaces.api.deps import stats_queries
from interfaces.api.params import SearchTerm
from interfaces.api.publication_filters import StatsFilters

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/facets", response_model=StatsFacetsResponse)
def stats_facets(
    filters: StatsFilters,
    queries: StatsQueries = Depends(stats_queries),
) -> StatsFacetsResponse:
    """Décomptes par option des facettes des tableaux de bord.

    Chaque facette écarte sa propre dimension de la clause WHERE : son décompte annonce le nombre de publications atteignables si l'option était cochée ou décochée.
    """
    return queries.stats_facets(filters=filters.to_filters())


@router.get("/facets/entities", response_model=EntityFacetResponse)
def stats_entity_facet(
    filters: StatsFilters,
    kind: EntityKind = Query(...),
    entity_search: SearchTerm = "",
    queries: StatsQueries = Depends(stats_queries),
) -> EntityFacetResponse:
    """Facette contextuelle des éditeurs, des revues ou des organisations partenaires : les premières entités sous les filtres actifs, avec leur décompte.

    Les entités sont corrélées entre elles. `entity_search` cherche dans leurs noms.
    """
    return queries.stats_entity_facet(kind=kind, search=entity_search, filters=filters.to_filters())


@router.get("/collaborations", response_model=CollaborationsResponse)
def collaborations(
    filters: StatsFilters,
    queries: StatsQueries = Depends(stats_queries),
) -> CollaborationsResponse:
    """Collaborations internationales : le nombre de publications co-affiliées à chaque pays étranger, sous les filtres actifs.

    Le décompte se lit dans la colonne `countries` des publications, le pays domestique écarté.
    """
    return queries.collaborations(filters=filters.to_filters())


@router.get("/pivot/schema", response_model=PivotSchemaResponse)
def pivot_schema(
    queries: StatsQueries = Depends(stats_queries),
) -> PivotSchemaResponse:
    """Vocabulaire du pivot (dimensions, indicateurs) dont l'interface tire ses sélecteurs."""
    return queries.pivot_schema()


@router.get("/pivot", response_model=PivotResponse)
def pivot(
    filters: StatsFilters,
    indicator: str = Query("doc_type_grouped"),
    compare: str = Query(""),
    queries: StatsQueries = Depends(stats_queries),
) -> PivotResponse:
    """Agrégation d'un indicateur, ventilé par sa dimension puis par l'axe `compare` s'il est renseigné, sous les filtres actifs.

    Un indicateur inconnu ou un axe non comparable donnent un 422.
    """
    return queries.indicator_pivot(
        indicator=indicator, compare=compare, filters=filters.to_filters()
    )
