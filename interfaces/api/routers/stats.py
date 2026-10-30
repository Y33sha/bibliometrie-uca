"""Router des agrégats des tableaux de bord, servis par `StatsQueries`. Sert `/api/stats/*`."""

from fastapi import APIRouter, Depends, Query

from infrastructure.read_models.stats.models import (
    CollaborationsResponse,
    PivotResponse,
    PivotSchemaResponse,
)
from infrastructure.read_models.stats.queries import StatsQueries
from interfaces.api.deps import stats_queries
from interfaces.api.publication_filters import StatsFilters

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/collaborations", response_model=CollaborationsResponse)
def collaborations(
    filters: StatsFilters,
    queries: StatsQueries = Depends(stats_queries),
) -> CollaborationsResponse:
    """Compte les publications co-affiliées à chaque pays étranger (collaborations internationales), sous les filtres actifs.

    Le décompte se lit dans la colonne `countries` des publications, le pays de l'établissement écarté.
    """
    return queries.collaborations(filters=filters.to_filters())


@router.get("/pivot/schema", response_model=PivotSchemaResponse)
def pivot_schema(
    queries: StatsQueries = Depends(stats_queries),
) -> PivotSchemaResponse:
    """Renvoie le vocabulaire du pivot (dimensions, indicateurs), source des sélecteurs de l'interface."""
    return queries.pivot_schema()


@router.get("/pivot", response_model=PivotResponse)
def pivot(
    filters: StatsFilters,
    indicator: str = Query("doc_type_grouped"),
    compare: str = Query(""),
    queries: StatsQueries = Depends(stats_queries),
) -> PivotResponse:
    """Agrège un indicateur, ventilé par sa dimension puis par l'axe `compare` s'il est renseigné, sous les filtres actifs.

    Un indicateur inconnu ou un axe non comparable donnent un 422.
    """
    return queries.indicator_pivot(
        indicator=indicator, compare=compare, filters=filters.to_filters()
    )
