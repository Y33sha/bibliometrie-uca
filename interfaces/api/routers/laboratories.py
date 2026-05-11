"""Router /api/laboratories/* — délègue au port `LaboratoriesQueries`."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.laboratories_queries import (
    LaboratoriesQueries,
    LabPersonsFilters,
)
from interfaces.api.deps import laboratories_queries_sync
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
def list_laboratories(
    queries: LaboratoriesQueries = Depends(laboratories_queries_sync),
) -> list[LaboratoryListItem]:
    """Liste des labos du périmètre."""
    return [LaboratoryListItem.model_validate(r) for r in queries.list_laboratories()]


@router.get("/api/laboratories/{lab_id}", response_model=LaboratoryDetailResponse)
def get_laboratory(
    lab_id: int,
    queries: LaboratoriesQueries = Depends(laboratories_queries_sync),
) -> LaboratoryDetailResponse:
    """Profil public d'un laboratoire."""
    result = queries.get_laboratory(lab_id)
    if not result:
        raise HTTPException(404, "Laboratory not found")
    return LaboratoryDetailResponse.model_validate(result)


@router.get("/api/laboratories/{lab_id}/persons", response_model=LaboratoryPersonsResponse)
def get_laboratory_persons(
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
    queries: LaboratoriesQueries = Depends(laboratories_queries_sync),
) -> LaboratoryPersonsResponse:
    """Personnes et authorships orphelines liées à un labo."""
    filters = LabPersonsFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_rh=has_rh,
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
    )
    return LaboratoryPersonsResponse.model_validate(
        queries.get_laboratory_persons(
            lab_id, filters=filters, page=page, per_page=per_page, sort=sort
        )
    )


@router.get("/api/laboratories/{lab_id}/addresses", response_model=LaboratoryAddressesResponse)
def get_laboratory_addresses(
    lab_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    queries: LaboratoriesQueries = Depends(laboratories_queries_sync),
) -> LaboratoryAddressesResponse:
    """Adresses liées à un laboratoire."""
    return LaboratoryAddressesResponse.model_validate(
        queries.get_laboratory_addresses(lab_id, page=page, per_page=per_page)
    )


@router.get("/api/laboratories/{lab_id}/dashboard", response_model=LaboratoryDashboardResponse)
def get_laboratory_dashboard(
    lab_id: int,
    queries: LaboratoriesQueries = Depends(laboratories_queries_sync),
) -> LaboratoryDashboardResponse:
    """Dashboard labo : publications par an + répartition OA."""
    return LaboratoryDashboardResponse.model_validate(queries.get_laboratory_dashboard(lab_id))


@router.get("/api/laboratories/{lab_id}/subjects", response_model=list[SubjectFrequency])
def get_laboratory_subjects(
    lab_id: int,
    limit: int = Query(30, ge=1, le=200),
    queries: LaboratoriesQueries = Depends(laboratories_queries_sync),
) -> list[SubjectFrequency]:
    """Top sujets des publications du labo (pour le nuage de mots dashboard)."""
    return [
        SubjectFrequency.model_validate(r)
        for r in queries.get_laboratory_subjects(lab_id, limit=limit)
    ]
