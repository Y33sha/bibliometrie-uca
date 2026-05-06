"""Router /api/stats/* — délègue les requêtes au port AsyncStatsQueries."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from application.ports.stats_queries import AsyncStatsQueries
from interfaces.api.async_deps import (
    get_root_structure_id,
    stats_queries,
)
from interfaces.api.filters import parse_int_csv
from interfaces.api.models import (
    JournalStatsResponse,
    LabStatsResponse,
    PublisherStatsResponse,
    StatsFacetsResponse,
    StatsSummary,
    YearStatsRow,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/stats/publishers", response_model=PublisherStatsResponse)
async def publisher_stats(
    lab_id: str = Query(""),
    year: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    sort: str = Query("-pubs"),
    queries: AsyncStatsQueries = Depends(stats_queries),
) -> Any:
    """Classement des éditeurs par volume de publications filtrées.

    `lab_id`, `year` : listes CSV d'entiers. `oa_status` : valeur
    unique (`gold`/`green`/`hybrid`/`bronze`/`closed`/`unknown`).
    `has_apc=yes|no|""` : filtre sur la présence d'un paiement APC
    connu.
    """
    return await queries.publisher_stats(
        root_structure_id=await get_root_structure_id(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        oa_status=oa_status,
        has_apc=has_apc,
        search=search,
        page=page,
        per_page=per_page,
        sort=sort,
    )


@router.get("/api/stats/journals", response_model=JournalStatsResponse)
async def journal_stats(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    sort: str = Query("-pubs"),
    queries: AsyncStatsQueries = Depends(stats_queries),
) -> Any:
    """Stats d'articles par revue."""
    return await queries.journal_stats(
        root_structure_id=await get_root_structure_id(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        oa_status=oa_status,
        has_apc=has_apc,
        search=search,
        page=page,
        per_page=per_page,
        sort=sort,
    )


@router.get("/api/stats/by-year", response_model=list[YearStatsRow])
async def stats_by_year(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    queries: AsyncStatsQueries = Depends(stats_queries),
) -> Any:
    """Ventilation par année (pour les graphiques)."""
    return await queries.stats_by_year(
        root_structure_id=await get_root_structure_id(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        journal_id=journal_id,
        oa_status=oa_status,
        has_apc=has_apc,
    )


@router.get("/api/stats/summary", response_model=StatsSummary)
async def stats_summary(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    queries: AsyncStatsQueries = Depends(stats_queries),
) -> Any:
    """Agrégats globaux (total, taux OA, total APC, etc.) pour le jeu de filtres."""
    return await queries.stats_summary(
        root_structure_id=await get_root_structure_id(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        journal_id=journal_id,
        oa_status=oa_status,
        has_apc=has_apc,
    )


@router.get("/api/stats/labs", response_model=LabStatsResponse)
async def stats_labs(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    sort: str = Query("-pubs"),
    queries: AsyncStatsQueries = Depends(stats_queries),
) -> Any:
    """Stats d'articles par laboratoire."""
    return await queries.stats_labs(
        root_structure_id=await get_root_structure_id(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        journal_id=journal_id,
        oa_status=oa_status,
        has_apc=has_apc,
        page=page,
        per_page=per_page,
        sort=sort,
    )


@router.get("/api/stats/years", response_model=list[int])
async def available_years(
    queries: AsyncStatsQueries = Depends(stats_queries),
) -> Any:
    """Liste des années présentes dans les publications validées (tri asc).

    Contrairement à `/api/publications/years` qui remonte toutes les
    années, celui-ci ne remonte que les années validées (config
    `years_validated`).
    """
    return await queries.available_years()


@router.get("/api/stats/facets", response_model=StatsFacetsResponse)
async def stats_facets(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    queries: AsyncStatsQueries = Depends(stats_queries),
) -> Any:
    """Facettes dynamiques : années, labos, oa_status, apc."""
    return await queries.stats_facets(
        root_structure_id=await get_root_structure_id(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        journal_id=journal_id,
        oa_status=oa_status,
        has_apc=has_apc,
    )
