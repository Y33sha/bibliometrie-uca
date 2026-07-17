"""Router /api/laboratories/* — les laboratoires du périmètre, servis par le port `LaboratoriesQueries`."""

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.api.laboratories_queries import (
    LaboratoriesQueries,
    LaboratoryAddressesResponse,
    LaboratoryDashboardResponse,
    LaboratoryDetailResponse,
    LaboratoryListItem,
)
from application.ports.api.subjects_queries import SubjectFrequency
from interfaces.api.deps import laboratories_queries

router = APIRouter()


@router.get("/api/laboratories", response_model=list[LaboratoryListItem])
def list_laboratories(
    queries: LaboratoriesQueries = Depends(laboratories_queries),
) -> list[LaboratoryListItem]:
    """Liste des laboratoires du périmètre, avec toutes leurs tutelles."""
    return queries.list_laboratories()


@router.get("/api/laboratories/{lab_id}", response_model=LaboratoryDetailResponse)
def get_laboratory(
    lab_id: int,
    queries: LaboratoriesQueries = Depends(laboratories_queries),
) -> LaboratoryDetailResponse:
    """Profil public d'un laboratoire."""
    result = queries.get_laboratory(lab_id)
    if not result:
        raise HTTPException(status_code=404, detail="Laboratoire introuvable")
    return result


@router.get("/api/laboratories/{lab_id}/addresses", response_model=LaboratoryAddressesResponse)
def get_laboratory_addresses(
    lab_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: LaboratoriesQueries = Depends(laboratories_queries),
) -> LaboratoryAddressesResponse:
    """Adresses liées à un laboratoire."""
    return queries.get_laboratory_addresses(lab_id, page=page, per_page=per_page)


@router.get("/api/laboratories/{lab_id}/dashboard", response_model=LaboratoryDashboardResponse)
def get_laboratory_dashboard(
    lab_id: int,
    queries: LaboratoriesQueries = Depends(laboratories_queries),
) -> LaboratoryDashboardResponse:
    """Agrégats du laboratoire : publications par année et répartition par statut d'accès ouvert."""
    return queries.get_laboratory_dashboard(lab_id)


@router.get("/api/laboratories/{lab_id}/subjects", response_model=list[SubjectFrequency])
def get_laboratory_subjects(
    lab_id: int,
    limit: int = Query(30, ge=1, le=200),
    queries: LaboratoriesQueries = Depends(laboratories_queries),
) -> list[SubjectFrequency]:
    """Sujets les plus fréquents des publications du laboratoire, pour le nuage de mots de son tableau de bord."""
    return queries.get_laboratory_subjects(lab_id, limit=limit)
