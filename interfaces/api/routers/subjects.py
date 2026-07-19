"""Router des sujets : liste paginée et détail avec les voisins par co-occurrence. Sert `/api/subjects/*`."""

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.api.subjects_queries import (
    SubjectDetailResponse,
    SubjectListResponse,
    SubjectsQueries,
)
from interfaces.api.deps import subjects_queries

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


@router.get("", response_model=SubjectListResponse)
def list_subjects(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    q: str | None = Query(
        None, description="Recherche sur le libellé, insensible à la casse et aux accents"
    ),
    min_count: int = Query(1, ge=1, description="Nombre minimal de publications portant le sujet"),
    queries: SubjectsQueries = Depends(subjects_queries),
) -> SubjectListResponse:
    """Liste paginée des sujets, les plus portés par des publications d'abord."""
    offset = (page - 1) * per_page
    items = queries.list_subjects(q=q, limit=per_page, offset=offset, min_usage_count=min_count)
    total = queries.count_subjects(q=q, min_usage_count=min_count)
    return SubjectListResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/{subject_id}", response_model=SubjectDetailResponse)
def get_subject(
    subject_id: int,
    neighbors_limit: int = Query(20, ge=1, le=100),
    min_cooccurrence: int = Query(2, ge=1),
    queries: SubjectsQueries = Depends(subjects_queries),
) -> SubjectDetailResponse:
    """Détail d'un sujet, avec ses voisins par co-occurrence, les plus fréquents d'abord."""
    subject = queries.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Sujet introuvable")
    neighbors = queries.get_subject_neighbors(
        subject_id, limit=neighbors_limit, min_cooccurrence_count=min_cooccurrence
    )
    return SubjectDetailResponse(subject=subject, neighbors=neighbors)
