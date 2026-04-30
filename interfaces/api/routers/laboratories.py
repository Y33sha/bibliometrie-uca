"""Router /api/laboratories/* — délègue à infrastructure/db/queries/laboratories.py."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from infrastructure.db.queries import laboratories as lab_queries
from infrastructure.perimeter import (
    async_get_persons_perimeter_root_ids,
    async_get_persons_structure_ids_list,
)
from interfaces.api.async_deps import get_async_cursor
from interfaces.api.filters import parse_str_csv
from interfaces.api.models import (
    LaboratoryAddressesResponse,
    LaboratoryDashboardResponse,
    LaboratoryDetailResponse,
    LaboratoryListItem,
    LaboratoryPersonsResponse,
    SubjectFrequency,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/laboratories", response_model=list[LaboratoryListItem])
async def list_laboratories() -> Any:
    """Liste des labos du périmètre."""
    async with get_async_cursor() as (cur, _conn):
        perimeter_ids = await async_get_persons_structure_ids_list(cur)
        root_ids = await async_get_persons_perimeter_root_ids(cur)
        return await lab_queries.list_laboratories(cur, perimeter_ids, root_ids)


@router.get("/api/laboratories/{lab_id}", response_model=LaboratoryDetailResponse)
async def get_laboratory(lab_id: int) -> Any:
    """Profil public d'un laboratoire."""
    async with get_async_cursor() as (cur, _conn):
        result = await lab_queries.get_laboratory(cur, lab_id)
        if not result:
            raise HTTPException(404, "Laboratory not found")
        return result


@router.get("/api/laboratories/{lab_id}/persons", response_model=LaboratoryPersonsResponse)
async def get_laboratory_persons(
    lab_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    sort: str = Query("name"),
    search: str = Query(""),
    department: str = Query(""),
    role: str = Query(""),
    has_rh: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_idref: str = Query(""),
) -> Any:
    """Personnes et authorships orphelines liées à un labo."""
    filters = lab_queries.LabPersonsFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_rh=has_rh,
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
    )
    async with get_async_cursor() as (cur, _conn):
        return await lab_queries.get_laboratory_persons(
            cur, lab_id, filters=filters, page=page, per_page=per_page, sort=sort
        )


@router.get("/api/laboratories/{lab_id}/addresses", response_model=LaboratoryAddressesResponse)
async def get_laboratory_addresses(
    lab_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Adresses liées à un laboratoire."""
    async with get_async_cursor() as (cur, _conn):
        return await lab_queries.get_laboratory_addresses(cur, lab_id, page=page, per_page=per_page)


@router.get("/api/laboratories/{lab_id}/dashboard", response_model=LaboratoryDashboardResponse)
async def get_laboratory_dashboard(lab_id: int) -> Any:
    """Dashboard labo : publications par an + répartition OA."""
    async with get_async_cursor() as (cur, _conn):
        return await lab_queries.get_laboratory_dashboard(cur, lab_id)


@router.get("/api/laboratories/{lab_id}/subjects", response_model=list[SubjectFrequency])
async def get_laboratory_subjects(
    lab_id: int,
    limit: int = Query(30, ge=1, le=200),
) -> Any:
    """Top sujets des publications du labo (pour le nuage de mots dashboard)."""
    async with get_async_cursor() as (cur, _conn):
        return await lab_queries.get_laboratory_subjects(cur, lab_id, limit=limit)
