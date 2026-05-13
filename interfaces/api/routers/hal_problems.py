"""Router HAL problems : diagnostics sur les dépôts HAL.

Regroupe les endpoints `/api/hal-problems/*` qui servent le tableau de
bord qualité HAL : comptes dupliqués, dépôts en double par DOI ou
métadonnées, publications manquant dans la collection d'un labo,
conflits d'affiliations inter-sources.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.api.hal_problems_queries import HalProblemsQueries
from interfaces.api.deps import hal_problems_queries_sync
from interfaces.api.models import (
    HalAffiliationConflictsResponse,
    HalCollectionLab,
    HalDoiDuplicatesResponse,
    HalDuplicateAccountsResponse,
    HalMetaDuplicatesResponse,
    HalMissingCollectionsResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/hal-problems/duplicate-accounts", response_model=HalDuplicateAccountsResponse)
def hal_duplicate_accounts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries_sync),
) -> HalDuplicateAccountsResponse:
    """Personnes liées à 2+ comptes HAL distincts."""
    return HalDuplicateAccountsResponse.model_validate(
        queries.hal_duplicate_accounts(page=page, per_page=per_page)
    )


@router.get("/api/hal-problems/duplicate-pubs-doi", response_model=HalDoiDuplicatesResponse)
def hal_duplicate_pubs_by_doi(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries_sync),
) -> HalDoiDuplicatesResponse:
    """Dépôts HAL avec DOI identique rattachés à la même publication."""
    return HalDoiDuplicatesResponse.model_validate(
        queries.hal_duplicate_pubs_by_doi(page=page, per_page=per_page)
    )


@router.get("/api/hal-problems/duplicate-pubs-meta", response_model=HalMetaDuplicatesResponse)
def hal_duplicate_pubs_by_metadata(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries_sync),
) -> HalMetaDuplicatesResponse:
    """Doublons possibles : dépôts HAL avec métadonnées identiques."""
    return HalMetaDuplicatesResponse.model_validate(
        queries.hal_duplicate_pubs_by_metadata(page=page, per_page=per_page)
    )


@router.get("/api/hal-problems/missing-collections", response_model=HalMissingCollectionsResponse)
def hal_missing_collections(
    lab_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries_sync),
) -> HalMissingCollectionsResponse:
    """Publications affiliées à un labo dans HAL mais absentes de sa collection."""
    result = queries.hal_missing_collections(lab_id=lab_id, page=page, per_page=per_page)
    if result.get("error") == "no_collection":
        raise HTTPException(status_code=400, detail="Labo sans collection HAL")
    return HalMissingCollectionsResponse.model_validate(result)


@router.get("/api/hal-problems/missing-collections/labs", response_model=list[HalCollectionLab])
def hal_missing_collections_labs(
    queries: HalProblemsQueries = Depends(hal_problems_queries_sync),
) -> list[HalCollectionLab]:
    """Liste des labos avec collection HAL."""
    return [HalCollectionLab.model_validate(r) for r in queries.hal_missing_collections_labs()]


@router.get(
    "/api/hal-problems/affiliation-conflicts", response_model=HalAffiliationConflictsResponse
)
def hal_affiliation_conflicts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries_sync),
) -> HalAffiliationConflictsResponse:
    """Publications affiliées UCA dans HAL mais pas dans une autre source."""
    return HalAffiliationConflictsResponse.model_validate(
        queries.hal_affiliation_conflicts(page=page, per_page=per_page)
    )
