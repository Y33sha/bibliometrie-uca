"""Router /api/stats/* — délègue les requêtes au port StatsQueries."""

import logging

from fastapi import APIRouter, Depends, Query

from application.ports.api.stats_queries import (
    PivotResponse,
    PivotSchemaResponse,
    StatsFacetsResponse,
    StatsQueries,
)
from interfaces.api.deps import (
    get_apc_structure_ids_sync,
    stats_queries_sync,
)
from interfaces.api.filters import parse_int_csv, parse_str_csv

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/stats/years", response_model=list[int])
def available_years(
    queries: StatsQueries = Depends(stats_queries_sync),
) -> list[int]:
    """Liste des années présentes dans les publications validées (tri asc, restreint via la config `years_validated`)."""
    return queries.available_years()


@router.get("/api/stats/facets", response_model=StatsFacetsResponse)
def stats_facets(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: str = Query(""),
    journal_id: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> StatsFacetsResponse:
    """Facettes dynamiques : années, labos, oa_status, apc."""
    return queries.stats_facets(
        apc_structure_ids=get_apc_structure_ids_sync(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_ids=parse_int_csv(publisher_id),
        journal_ids=parse_int_csv(journal_id),
        oa_status=oa_status,
        has_apc=has_apc,
        doc_types=parse_str_csv(doc_type),
    )


@router.get("/api/stats/pivot/schema", response_model=PivotSchemaResponse)
def pivot_schema(
    queries: StatsQueries = Depends(stats_queries_sync),
) -> PivotSchemaResponse:
    """Vocabulaire du pivot (dimensions groupables, mesures) dont l'interface tire ses sélecteurs."""
    return queries.pivot_schema()


@router.get("/api/stats/pivot", response_model=PivotResponse)
def pivot(
    measure: str = Query("pub_count"),
    group: str = Query(""),
    group2: str = Query(""),
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: str = Query(""),
    journal_id: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> PivotResponse:
    """Agrégation générique : `measure` ventilée selon `group` (primaire) et `group2` (secondaire),
    sous les filtres. Clés validées contre le registre (400 si inconnues)."""
    groups = [g for g in (group, group2) if g]
    return queries.pivot(
        measure=measure,
        groups=groups,
        apc_structure_ids=get_apc_structure_ids_sync(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_ids=parse_int_csv(publisher_id),
        journal_ids=parse_int_csv(journal_id),
        oa_status=oa_status,
        has_apc=has_apc,
        doc_types=parse_str_csv(doc_type),
    )
