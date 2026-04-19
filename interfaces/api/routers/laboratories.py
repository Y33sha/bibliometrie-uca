"""Router /api/laboratories/* — délègue à infrastructure/db/queries/laboratories.py."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from infrastructure.db.queries import laboratories as lab_queries
from interfaces.api.deps import get_cursor

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/laboratories")
async def list_laboratories() -> Any:
    """Liste des labos du périmètre."""
    with get_cursor() as (cur, _conn):
        return lab_queries.list_laboratories(cur)


@router.get("/api/laboratories/{lab_id}")
async def get_laboratory(lab_id: int) -> Any:
    """Profil public d'un laboratoire."""
    with get_cursor() as (cur, _conn):
        result = lab_queries.get_laboratory(cur, lab_id)
        if not result:
            raise HTTPException(404, "Laboratory not found")
        return result


@router.get("/api/laboratories/{lab_id}/persons")
async def get_laboratory_persons(
    lab_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    sort: str = Query("name"),
    search: str = Query(""),
    has_rh: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
) -> Any:
    """Personnes et authorships orphelines liées à un labo."""
    filters = lab_queries.LabPersonsFilters(
        search=search,
        has_rh=has_rh,
        has_orcid=has_orcid,
        has_idhal=has_idhal,
    )
    with get_cursor() as (cur, _conn):
        return lab_queries.get_laboratory_persons(
            cur, lab_id, filters=filters, page=page, per_page=per_page, sort=sort
        )


@router.get("/api/laboratories/{lab_id}/addresses")
async def get_laboratory_addresses(
    lab_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Adresses liées à un laboratoire."""
    with get_cursor() as (cur, _conn):
        return lab_queries.get_laboratory_addresses(cur, lab_id, page=page, per_page=per_page)


@router.get("/api/laboratories/{lab_id}/dashboard")
async def get_laboratory_dashboard(lab_id: int) -> Any:
    """Dashboard labo : publications par an + répartition OA."""
    with get_cursor() as (cur, _conn):
        return lab_queries.get_laboratory_dashboard(cur, lab_id)
