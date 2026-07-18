"""Router des anomalies des dépôts HAL. Sert `/api/hal-problems/*`.

Alimente le tableau de bord qualité HAL : comptes d'auteur dupliqués, dépôts en double par identifiant ou par métadonnées, publications absentes de la collection de leur laboratoire, affiliations en conflit d'une source à l'autre.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.api.hal_problems_queries import (
    HalAffiliationConflictsResponse,
    HalCollectionLab,
    HalDoiDuplicatesResponse,
    HalDuplicateAccountsResponse,
    HalMetaDuplicatesResponse,
    HalMissingCollectionsResponse,
    HalProblemsQueries,
    NoMissingCollections,
)
from interfaces.api.deps import hal_problems_queries

router = APIRouter(prefix="/api/hal-problems", tags=["hal-problems"])


@router.get("/duplicate-accounts", response_model=HalDuplicateAccountsResponse)
def hal_duplicate_accounts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> HalDuplicateAccountsResponse:
    """Personnes liées à 2+ comptes HAL distincts."""
    return queries.hal_duplicate_accounts(page=page, per_page=per_page)


@router.get("/duplicate-pubs-doi", response_model=HalDoiDuplicatesResponse)
def hal_duplicate_pubs_by_doi(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> HalDoiDuplicatesResponse:
    """Dépôts HAL avec DOI identique rattachés à la même publication."""
    return queries.hal_duplicate_pubs_by_doi(page=page, per_page=per_page)


@router.get("/duplicate-pubs-meta", response_model=HalMetaDuplicatesResponse)
def hal_duplicate_pubs_by_metadata(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> HalMetaDuplicatesResponse:
    """Doublons possibles : dépôts HAL avec métadonnées identiques."""
    return queries.hal_duplicate_pubs_by_metadata(page=page, per_page=per_page)


@router.get("/missing-collections", response_model=HalMissingCollectionsResponse)
def hal_missing_collections(
    lab_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> HalMissingCollectionsResponse:
    """Publications affiliées à un laboratoire dans HAL mais absentes de sa collection.

    Renvoie 404 sur un laboratoire introuvable, 400 sur un laboratoire dont aucune collection HAL n'est configurée — la question est sans objet, faute de collection à laquelle comparer.
    """
    result = queries.hal_missing_collections(lab_id=lab_id, page=page, per_page=per_page)
    if result is NoMissingCollections.UNKNOWN_LAB:
        raise HTTPException(status_code=404, detail="Laboratoire introuvable")
    if result is NoMissingCollections.NO_COLLECTION:
        raise HTTPException(status_code=400, detail="Laboratoire sans collection HAL")
    return result


@router.get("/missing-collections/labs", response_model=list[HalCollectionLab])
def hal_missing_collections_labs(
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> list[HalCollectionLab]:
    """Liste des labos avec collection HAL."""
    return queries.hal_missing_collections_labs()


@router.get("/affiliation-conflicts", response_model=HalAffiliationConflictsResponse)
def hal_affiliation_conflicts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> HalAffiliationConflictsResponse:
    """Publications affiliées UCA dans HAL mais pas dans une autre source."""
    return queries.hal_affiliation_conflicts(page=page, per_page=per_page)
