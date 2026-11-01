"""Router des sujets : liste paginée, facettes, export et détail avec les voisins par co-occurrence. Sert `/api/subjects/*`.

Un sujet regroupe les sujets de vocabulaire de même libellé normalisé : le libellé normalisé l'identifie. Les chemins littéraux `/export.csv` et `/facets` précèdent `/{label_normalized}`, qui les accepterait sinon comme identifiant.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from domain.subjects.subject import SubjectVocabulary
from infrastructure.read_models.subjects.models import (
    SubjectDetailResponse,
    SubjectFilters,
    SubjectListResponse,
    SubjectsFacetsResponse,
    SubjectSort,
)
from infrastructure.read_models.subjects.queries import SubjectsQueries
from interfaces.api.csv_export import csv_response
from interfaces.api.deps import subjects_queries
from interfaces.api.filters import parse_vocabulary_csv
from interfaces.api.params import SearchTerm
from interfaces.api.rate_limit import ExportSlot, export_rate_limit, export_slot

router = APIRouter(prefix="/api/subjects", tags=["subjects"])

_VOCABULARIES = frozenset(v.value for v in SubjectVocabulary)


def subject_filters(search: SearchTerm = "", vocabulary: str = "") -> SubjectFilters:
    """Lit les filtres partagés par la liste, son export et ses facettes.

    `search` vise le libellé, sans égard à la casse ni aux accents. `vocabulary` liste, séparés par des virgules, les vocabulaires retenus.
    """
    return SubjectFilters(
        search=search,
        vocabularies=tuple(
            parse_vocabulary_csv(vocabulary, allowed=_VOCABULARIES, param="vocabulary")
        ),
    )


@router.get("", response_model=SubjectListResponse)
def list_subjects(
    filters: SubjectFilters = Depends(subject_filters),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: SubjectSort = "publications_desc",
    queries: SubjectsQueries = Depends(subjects_queries),
) -> SubjectListResponse:
    """Liste les sujets par page, avec leur nombre de publications."""
    return queries.list_subjects(filters=filters, sort=sort, page=page, per_page=per_page)


@router.get("/facets", response_model=SubjectsFacetsResponse)
def subjects_facets(
    filters: SubjectFilters = Depends(subject_filters),
    queries: SubjectsQueries = Depends(subjects_queries),
) -> SubjectsFacetsResponse:
    """Compte les sujets de chaque vocabulaire. Le décompte écarte le filtre des vocabulaires."""
    return queries.subjects_facets(filters=filters)


@router.get("/export.csv")
def export_subjects_csv(
    filters: SubjectFilters = Depends(subject_filters),
    sort: SubjectSort = "publications_desc",
    queries: SubjectsQueries = Depends(subjects_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Exporte en CSV la liste des sujets, aux filtres et au tri de la liste."""
    return csv_response(
        queries.export_subjects_csv(filters=filters, sort=sort),
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
