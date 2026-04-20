"""Router /api/stats/* — délègue les requêtes à infrastructure/db/queries/stats.py."""

import logging
from typing import Any

from fastapi import APIRouter, Query

from infrastructure.db.queries import stats as stats_queries
from interfaces.api.deps import get_cursor, get_root_structure_id
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
) -> Any:
    """Stats d'articles par éditeur."""
    with get_cursor() as (cur, _conn):
        return stats_queries.publisher_stats(
            cur,
            root_structure_id=get_root_structure_id(),
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
) -> Any:
    """Stats d'articles par revue."""
    with get_cursor() as (cur, _conn):
        return stats_queries.journal_stats(
            cur,
            root_structure_id=get_root_structure_id(),
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
) -> Any:
    """Ventilation par année (pour les graphiques)."""
    with get_cursor() as (cur, _conn):
        return stats_queries.stats_by_year(
            cur,
            root_structure_id=get_root_structure_id(),
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
) -> Any:
    """Résumé global."""
    with get_cursor() as (cur, _conn):
        return stats_queries.stats_summary(
            cur,
            root_structure_id=get_root_structure_id(),
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
) -> Any:
    """Stats d'articles par laboratoire."""
    with get_cursor() as (cur, _conn):
        return stats_queries.stats_labs(
            cur,
            root_structure_id=get_root_structure_id(),
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
async def available_years() -> Any:
    """Années disponibles (validées uniquement)."""
    with get_cursor() as (cur, _conn):
        return stats_queries.available_years(cur)


@router.get("/api/stats/facets", response_model=StatsFacetsResponse)
async def stats_facets(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
) -> Any:
    """Facettes dynamiques : années, labos, oa_status, apc (chaque facette
    exclut son propre filtre mais applique tous les autres)."""
    with get_cursor() as (cur, _conn):
        return stats_queries.stats_facets(
            cur,
            root_structure_id=get_root_structure_id(),
            lab_ids=parse_int_csv(lab_id),
            years=parse_int_csv(year),
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
        )
