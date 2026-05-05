"""Router HAL problems : diagnostics sur les dépôts HAL.

Regroupe les endpoints d'audit HAL : comptes dupliqués, dépôts en double
par DOI ou métadonnées, publications manquant dans la collection d'un
labo, conflits d'affiliations inter-sources.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from infrastructure.db.queries import hal_problems as hal_queries
from infrastructure.db.queries.persons import admin as persons_admin_queries
from interfaces.api.async_deps import get_async_cursor
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
async def hal_duplicate_accounts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Personnes liées à 2+ comptes HAL distincts."""
    async with get_async_cursor() as (cur, _conn):
        return await persons_admin_queries.hal_duplicate_accounts(cur, page=page, per_page=per_page)


@router.get("/api/hal-problems/duplicate-pubs-doi", response_model=HalDoiDuplicatesResponse)
async def hal_duplicate_pubs_by_doi(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Dépôts HAL avec DOI identique rattachés à la même publication."""
    async with get_async_cursor() as (cur, _conn):
        return await hal_queries.hal_duplicate_pubs_by_doi(cur, page=page, per_page=per_page)


@router.get("/api/hal-problems/duplicate-pubs-meta", response_model=HalMetaDuplicatesResponse)
async def hal_duplicate_pubs_by_metadata(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Doublons possibles : dépôts HAL avec métadonnées identiques."""
    async with get_async_cursor() as (cur, _conn):
        return await hal_queries.hal_duplicate_pubs_by_metadata(cur, page=page, per_page=per_page)


@router.get("/api/hal-problems/missing-collections", response_model=HalMissingCollectionsResponse)
async def hal_missing_collections(
    lab_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Publications affiliées à un labo dans HAL mais absentes de sa collection."""
    async with get_async_cursor() as (cur, _conn):
        result = await hal_queries.hal_missing_collections(
            cur, lab_id=lab_id, page=page, per_page=per_page
        )
        if result.get("error") == "no_collection":
            raise HTTPException(status_code=400, detail="Labo sans collection HAL")
        return result


@router.get("/api/hal-problems/missing-collections/labs", response_model=list[HalCollectionLab])
async def hal_missing_collections_labs() -> Any:
    """Liste des labos avec collection HAL."""
    async with get_async_cursor() as (cur, _conn):
        return await hal_queries.hal_missing_collections_labs(cur)


@router.get(
    "/api/hal-problems/affiliation-conflicts", response_model=HalAffiliationConflictsResponse
)
async def hal_affiliation_conflicts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Publications affiliées UCA dans HAL mais pas dans une autre source."""
    async with get_async_cursor() as (cur, _conn):
        return await hal_queries.hal_affiliation_conflicts(cur, page=page, per_page=per_page)
