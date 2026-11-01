"""Router des sujets : liste paginée, export et détail avec les voisins par co-occurrence. Sert `/api/subjects/*`.

Un sujet regroupe les sujets de vocabulaire de même libellé normalisé : le libellé normalisé l'identifie. Le chemin littéral `/export.csv` précède `/{label_normalized}`, qui l'accepterait sinon comme identifiant.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from infrastructure.read_models.subjects.models import (
    SubjectDetailResponse,
    SubjectListResponse,
    SubjectSort,
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


Filters = Annotated[SubjectFilterParams, Depends()]


@router.get("", response_model=SubjectListResponse)
def list_subjects(
    filters: Filters,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: SubjectSort = "publications_desc",
    queries: SubjectsQueries = Depends(subjects_queries),
) -> SubjectListResponse:
    """Liste les sujets par page, avec leur nombre de publications."""
    return queries.list_subjects(search=filters.search, sort=sort, page=page, per_page=per_page)


@router.get("/export.csv")
def export_subjects_csv(
    filters: Filters,
    sort: SubjectSort = "publications_desc",
    queries: SubjectsQueries = Depends(subjects_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Exporte en CSV la liste des sujets, aux filtres et au tri de la liste."""
    return csv_response(
        queries.export_subjects_csv(search=filters.search, sort=sort),
        filename="sujets.csv",
        slot=slot,
    )


@router.get("/{label_normalized}", response_model=SubjectDetailResponse)
def get_subject(
    label_normalized: str,
    neighbors_limit: int = Query(20, ge=1, le=100),
    min_cooccurrence: int = Query(2, ge=1),
    queries: SubjectsQueries = Depends(subjects_queries),
) -> SubjectDetailResponse:
    """Renvoie le détail d'un sujet, identifié par son libellé normalisé, avec ses voisins par co-occurrence, les plus fréquents d'abord."""
    detail = queries.get_subject_detail(
        label_normalized, neighbors_limit=neighbors_limit, min_cooccurrence_count=min_cooccurrence
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Sujet introuvable")
    return detail
