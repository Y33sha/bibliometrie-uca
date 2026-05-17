"""Router Sujets — liste, détail, voisins par co-occurrence."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.api.subjects_queries import SubjectsAdminQueries
from application.subjects.dtos import SubjectDetailResponse, SubjectListResponse
from interfaces.api.deps import subjects_admin_queries

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/subjects", response_model=SubjectListResponse)
def list_subjects(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, description="Recherche insensible à la casse sur label"),
    min_count: int = Query(1, ge=1, description="Filtre usage_count >= min_count"),
    queries: SubjectsAdminQueries = Depends(subjects_admin_queries),
) -> SubjectListResponse:
    """Liste paginée des sujets, ordonnée par `usage_count` décroissant."""
    offset = (page - 1) * per_page
    items = queries.list_subjects(q=q, limit=per_page, offset=offset, min_count=min_count)
    total = queries.count_subjects(q=q, min_count=min_count)
    return SubjectListResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/api/subjects/{subject_id}", response_model=SubjectDetailResponse)
def get_subject(
    subject_id: int,
    neighbors_limit: int = Query(20, ge=1, le=100),
    min_cooccurrence: int = Query(2, ge=1),
    queries: SubjectsAdminQueries = Depends(subjects_admin_queries),
) -> SubjectDetailResponse:
    """Détail d'un sujet + ses voisins par co-occurrence (top N)."""
    subject = queries.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    neighbors = queries.get_subject_neighbors(
        subject_id, limit=neighbors_limit, min_count=min_cooccurrence
    )
    return SubjectDetailResponse(subject=subject, neighbors=neighbors)
