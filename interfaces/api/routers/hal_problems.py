"""Router des anomalies des dépôts HAL. Sert `/api/hal-problems/*`.

Alimente le tableau de bord qualité HAL : comptes d'auteur dupliqués, dépôts en double par identifiant ou par métadonnées, publications absentes de la collection de leur laboratoire, affiliations en conflit d'une source à l'autre.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from infrastructure.read_models.hal_problems.models import (
    HalAffiliationConflictsResponse,
    HalCollectionLab,
    HalDoiDuplicatesResponse,
    HalDuplicateAccountsResponse,
    HalMetaDuplicatesResponse,
    HalMissingCollectionsResponse,
    NoMissingCollections,
)
from infrastructure.read_models.hal_problems.queries import HalProblemsQueries
from interfaces.api.csv_export import csv_response
from interfaces.api.deps import hal_problems_queries
from interfaces.api.rate_limit import ExportSlot, export_rate_limit, export_slot

router = APIRouter(prefix="/api/hal-problems", tags=["hal-problems"])


@router.get("/duplicate-accounts", response_model=HalDuplicateAccountsResponse)
def hal_duplicate_accounts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> HalDuplicateAccountsResponse:
    """Personnes liées à 2+ comptes HAL distincts."""
    return queries.hal_duplicate_accounts(page=page, per_page=per_page)


@router.get("/duplicate-publications-doi", response_model=HalDoiDuplicatesResponse)
def hal_duplicate_publications_by_doi(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> HalDoiDuplicatesResponse:
    """Dépôts HAL avec DOI identique rattachés à la même publication."""
    return queries.hal_duplicate_publications_by_doi(page=page, per_page=per_page)


@router.get("/duplicate-publications-meta", response_model=HalMetaDuplicatesResponse)
def hal_duplicate_publications_by_metadata(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> HalMetaDuplicatesResponse:
    """Doublons possibles : dépôts HAL avec métadonnées identiques."""
    return queries.hal_duplicate_publications_by_metadata(page=page, per_page=per_page)


@router.get("/missing-collections", response_model=HalMissingCollectionsResponse)
def hal_missing_collections(
    lab_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
) -> HalMissingCollectionsResponse:
    """Publications affiliées à un laboratoire dans HAL mais absentes de sa collection.

    Renvoie 404 sur un laboratoire introuvable, 422 sur un laboratoire dont aucune collection HAL n'est configurée — la question est sans objet, faute de collection à laquelle comparer.
    """
    result = queries.hal_missing_collections(lab_id=lab_id, page=page, per_page=per_page)
    if result is NoMissingCollections.UNKNOWN_LAB:
        raise HTTPException(status_code=404, detail="Laboratoire introuvable")
    if result is NoMissingCollections.NO_COLLECTION:
        raise HTTPException(status_code=422, detail="Laboratoire sans collection HAL")
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
    """Publications affiliées à l'établissement dans HAL mais pas dans une autre source."""
    return queries.hal_affiliation_conflicts(page=page, per_page=per_page)


# ── Exports CSV ──────────────────────────────────────────────────


@router.get("/duplicate-accounts/export.csv")
def export_duplicate_accounts_csv(
    queries: HalProblemsQueries = Depends(hal_problems_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV des comptes auteur HAL en double."""
    return csv_response(
        queries.export_duplicate_accounts_csv(),
        filename="comptes-hal-en-double.csv",
        slot=slot,
    )


@router.get("/duplicate-publications-doi/export.csv")
def export_duplicate_publications_by_doi_csv(
    queries: HalProblemsQueries = Depends(hal_problems_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV des dépôts HAL en double par DOI."""
    return csv_response(
        queries.export_duplicate_publications_by_doi_csv(),
        filename="depots-hal-en-double-doi.csv",
        slot=slot,
    )


@router.get("/duplicate-publications-meta/export.csv")
def export_duplicate_publications_by_metadata_csv(
    queries: HalProblemsQueries = Depends(hal_problems_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV des doublons possibles de dépôts HAL par métadonnées."""
    return csv_response(
        queries.export_duplicate_publications_by_metadata_csv(),
        filename="depots-hal-en-double-metadonnees.csv",
        slot=slot,
    )


@router.get("/missing-collections/export.csv")
def export_missing_collections_csv(
    lab_id: int = Query(...),
    queries: HalProblemsQueries = Depends(hal_problems_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV des publications d'un laboratoire absentes de sa collection HAL.

    Renvoie 404 et 422 dans les mêmes cas que la liste.
    """
    result = queries.export_missing_collections_csv(lab_id=lab_id)
    if result is NoMissingCollections.UNKNOWN_LAB:
        raise HTTPException(status_code=404, detail="Laboratoire introuvable")
    if result is NoMissingCollections.NO_COLLECTION:
        raise HTTPException(status_code=422, detail="Laboratoire sans collection HAL")
    return csv_response(result, filename="publications-absentes-des-collections.csv", slot=slot)


@router.get("/affiliation-conflicts/export.csv")
def export_affiliation_conflicts_csv(
    queries: HalProblemsQueries = Depends(hal_problems_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV des publications aux affiliations HAL divergentes."""
    return csv_response(
        queries.export_affiliation_conflicts_csv(),
        filename="affiliations-hal-divergentes.csv",
        slot=slot,
    )
