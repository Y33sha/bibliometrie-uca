"""Router des sujets : liste paginée, export et détail avec les voisins par co-occurrence. Sert `/api/subjects/*`.

Le chemin littéral `/export.csv` précède `/{subject_id}`, qui l'accepterait sinon comme identifiant.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from infrastructure.read_models.subjects.models import (
    SubjectDetailResponse,
    SubjectListResponse,
)
from infrastructure.read_models.subjects.queries import SubjectsQueries
from interfaces.api.csv_export import csv_response
from interfaces.api.deps import subjects_queries
from interfaces.api.params import MAX_SEARCH_LENGTH
from interfaces.api.rate_limit import ExportSlot, export_rate_limit, export_slot

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


@dataclass(frozen=True, slots=True)
class SubjectFilterParams:
    """Filtres de la liste des sujets et de son export."""

    search: Annotated[
        str | None,
        Query(
            max_length=MAX_SEARCH_LENGTH,
            description="Recherche sur le libellé, insensible à la casse et aux accents",
        ),
    ] = None
    min_count: Annotated[
        int, Query(ge=1, description="Nombre minimal de publications portant le sujet")
    ] = 1


Filters = Annotated[SubjectFilterParams, Depends()]


@router.get("", response_model=SubjectListResponse)
def list_subjects(
    filters: Filters,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: SubjectsQueries = Depends(subjects_queries),
) -> SubjectListResponse:
    """Liste paginée des sujets, les plus portés par des publications d'abord."""
    return queries.list_subjects(
        search=filters.search, page=page, per_page=per_page, min_usage_count=filters.min_count
    )


@router.get("/export.csv")
def export_subjects_csv(
    filters: Filters,
    queries: SubjectsQueries = Depends(subjects_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV de la liste des sujets, aux filtres et au tri de la liste."""
    return csv_response(
        queries.export_subjects_csv(search=filters.search, min_usage_count=filters.min_count),
        filename="sujets.csv",
        slot=slot,
    )


@router.get("/{subject_id}", response_model=SubjectDetailResponse)
def get_subject(
    subject_id: int,
    neighbors_limit: int = Query(20, ge=1, le=100),
    min_cooccurrence: int = Query(2, ge=1),
    queries: SubjectsQueries = Depends(subjects_queries),
) -> SubjectDetailResponse:
    """Détail d'un sujet, avec ses voisins par co-occurrence, les plus fréquents d'abord."""
    detail = queries.get_subject_detail(
        subject_id, neighbors_limit=neighbors_limit, min_cooccurrence_count=min_cooccurrence
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Sujet introuvable")
    return detail
