"""Router Sujets — liste, détail, voisins par co-occurrence."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from infrastructure.db.queries.subjects import (
    count_subjects_async,
    get_subject_async,
    get_subject_neighbors_async,
    list_subjects_async,
)
from interfaces.api.async_deps import get_async_cursor
from interfaces.api.models import SubjectDetailResponse, SubjectListResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/subjects", response_model=SubjectListResponse)
async def list_subjects(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, description="Recherche insensible à la casse sur label"),
    min_count: int = Query(1, ge=1, description="Filtre usage_count >= min_count"),
) -> Any:
    """Liste paginée des sujets, ordonnée par `usage_count` décroissant."""
    offset = (page - 1) * per_page
    async with get_async_cursor() as (cur, _conn):
        items = await list_subjects_async(
            cur, q=q, limit=per_page, offset=offset, min_count=min_count
        )
        total = await count_subjects_async(cur, q=q, min_count=min_count)
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/api/subjects/{subject_id}", response_model=SubjectDetailResponse)
async def get_subject(
    subject_id: int,
    neighbors_limit: int = Query(20, ge=1, le=100),
    min_cooccurrence: int = Query(2, ge=1),
) -> Any:
    """Détail d'un sujet + ses voisins par co-occurrence (top N)."""
    async with get_async_cursor() as (cur, _conn):
        subject = await get_subject_async(cur, subject_id)
        if subject is None:
            raise HTTPException(status_code=404, detail="Subject not found")
        neighbors = await get_subject_neighbors_async(
            cur, subject_id, limit=neighbors_limit, min_count=min_cooccurrence
        )
    return {"subject": subject, "neighbors": neighbors}
