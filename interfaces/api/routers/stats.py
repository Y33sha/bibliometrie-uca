"""Router /api/stats/* — délègue les requêtes au port StatsQueries."""

import logging

from fastapi import APIRouter, Depends, Query

from application.ports.api.stats_queries import (
    JournalStatsResponse,
    PivotResponse,
    PivotSchemaResponse,
    PublisherStatsResponse,
    StatsFacetsResponse,
    StatsQueries,
    YearStatsRow,
)
from interfaces.api.deps import (
    get_apc_structure_ids_sync,
    stats_queries_sync,
)
from interfaces.api.filters import parse_int_csv, parse_str_csv

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/stats/publishers", response_model=PublisherStatsResponse)
def publisher_stats(
    lab_id: str = Query(""),
    year: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    sort: str = Query("-pubs"),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> PublisherStatsResponse:
    """Classement des éditeurs par volume de publications filtrées.

    `lab_id`, `year` : listes CSV d'entiers. `oa_status` : valeur unique (`gold`/`green`/`hybrid`/`bronze`/`closed`/`unknown`). `has_apc=yes|no|""` : filtre sur la présence d'un paiement APC connu.
    """
    return queries.publisher_stats(
        apc_structure_ids=get_apc_structure_ids_sync(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        oa_status=oa_status,
        has_apc=has_apc,
        doc_types=parse_str_csv(doc_type),
        search=search,
        page=page,
        per_page=per_page,
        sort=sort,
    )


@router.get("/api/stats/journals", response_model=JournalStatsResponse)
def journal_stats(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    sort: str = Query("-pubs"),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> JournalStatsResponse:
    """Stats d'articles par revue."""
    return queries.journal_stats(
        apc_structure_ids=get_apc_structure_ids_sync(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        oa_status=oa_status,
        has_apc=has_apc,
        doc_types=parse_str_csv(doc_type),
        search=search,
        page=page,
        per_page=per_page,
        sort=sort,
    )


@router.get("/api/stats/by-year", response_model=list[YearStatsRow])
def stats_by_year(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> list[YearStatsRow]:
    """Ventilation par année (pour les graphiques)."""
    return queries.stats_by_year(
        apc_structure_ids=get_apc_structure_ids_sync(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        journal_id=journal_id,
        oa_status=oa_status,
        has_apc=has_apc,
        doc_types=parse_str_csv(doc_type),
    )


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
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
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
        publisher_id=publisher_id,
        journal_id=journal_id,
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
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
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
        publisher_id=publisher_id,
        journal_id=journal_id,
        oa_status=oa_status,
        has_apc=has_apc,
        doc_types=parse_str_csv(doc_type),
    )
