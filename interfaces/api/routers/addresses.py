"""Router /api/addresses/* et /api/countries.

Lectures : port `AsyncAddressesQueries`. Mutations : services applicatifs
- `application.addresses_structures` pour les liens adresse↔structure
- `application.addresses_countries` pour l'attribution et propagation des pays.
"""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from application import addresses_countries as countries_service
from application import addresses_structures as structures_service
from application.ports.addresses_queries import (
    AddressCountriesFilters,
    AddressListFilters,
    AsyncAddressesQueries,
)
from domain.ports.address_repository import AsyncAddressRepository
from domain.ports.authorship_repository import AsyncAuthorshipRepository
from domain.ports.structure_repository import AsyncStructureRepository
from interfaces.api.async_deps import (
    address_repo,
    addresses_queries,
    authorship_repo,
    bg_propagate_countries,
    db_conn,
    get_perimeter_queries,
    structure_repo,
)
from interfaces.api.deps import require_admin
from interfaces.api.models import (
    AddressesCountriesResponse,
    AddressListResponse,
    AddressPublicationsResponse,
    AddressReviewResponse,
    AddressStatsResponse,
    AssignStructureAction,
    AssignStructureResponse,
    BatchCountryResponse,
    BatchReviewAction,
    BatchSetCountry,
    BatchUpdatedResponse,
    CountryOut,
    CountrySuggestionsResponse,
    OkResponse,
    ReviewAction,
    SetCountry,
    UnassignStructureResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/addresses", response_model=AddressListResponse)
async def list_addresses(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    structure_id: int | None = Query(None),
    detected: str = Query("yes"),
    validation: str = Query("pending"),
    search: str = Query(""),
    search_mode: str = Query("contains"),
    queries: AsyncAddressesQueries = Depends(addresses_queries),
) -> Any:
    """Liste les adresses avec filtres détection/validation pour une structure."""
    # Garde-fou : mode "non détecté"/"tous" sans filtre → trop large
    if detected in ("no", "all") and not search and validation in ("all", "pending"):
        return {
            "total": 0,
            "page": 1,
            "per_page": per_page,
            "pages": 0,
            "addresses": [],
            "requires_search": True,
        }

    filters = AddressListFilters(
        detected=detected,
        validation=validation,
        search=search,
        search_mode=search_mode,
    )
    sid = structure_id if structure_id is not None else await queries.resolve_default_structure_id()
    return await queries.list_addresses(
        structure_id=sid, filters=filters, page=page, per_page=per_page
    )


@router.get("/api/addresses/{addr_id}/publications", response_model=AddressPublicationsResponse)
async def get_address_publications(
    addr_id: int,
    limit: int = Query(20),
    queries: AsyncAddressesQueries = Depends(addresses_queries),
) -> Any:
    """Échantillon de publications liées à une adresse."""
    addr = await queries.get_address_basic(addr_id)
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")
    publications = await queries.get_address_publications(addr_id, limit)
    return {
        "address_id": addr_id,
        "raw_text": addr["raw_text"],
        "publications": publications,
    }


@router.post("/api/addresses/{addr_id}/review", response_model=AddressReviewResponse)
async def review_address(
    addr_id: int,
    action: ReviewAction,
    conn: AsyncConnection = Depends(db_conn),
    queries: AsyncAddressesQueries = Depends(addresses_queries),
    addr_repo: AsyncAddressRepository = Depends(address_repo),
    auth_repo: AsyncAuthorshipRepository = Depends(authorship_repo),
) -> Any:
    """Confirme, rejette ou reset le lien adresse ↔ structure."""
    await structures_service.review_structure_link(
        conn,
        addr_id,
        action.structure_id,
        action.is_confirmed,
        repo=addr_repo,
        authorship_repo=auth_repo,
        perimeter_queries=get_perimeter_queries(),
    )
    structures = await queries.get_address_structures(addr_id)
    link = await queries.get_structure_link(addr_id, action.structure_id)
    return {
        "id": addr_id,
        "is_confirmed": link["is_confirmed"] if link else None,
        "is_detected": link["is_detected"] if link else False,
        "structures": structures,
    }


@router.post("/api/addresses/batch-review", response_model=BatchUpdatedResponse)
async def batch_review(
    data: BatchReviewAction,
    conn: AsyncConnection = Depends(db_conn),
    addr_repo: AsyncAddressRepository = Depends(address_repo),
    auth_repo: AsyncAuthorshipRepository = Depends(authorship_repo),
) -> Any:
    """Confirme/rejette/reset en batch."""
    updated = await structures_service.batch_review_structure_link(
        conn,
        data.address_ids,
        data.structure_id,
        data.is_confirmed,
        repo=addr_repo,
        authorship_repo=auth_repo,
        perimeter_queries=get_perimeter_queries(),
    )
    return {"updated": updated}


@router.get("/api/countries", response_model=list[CountryOut])
async def list_countries(
    queries: AsyncAddressesQueries = Depends(addresses_queries),
) -> Any:
    """Liste des pays."""
    return await queries.list_countries()


@router.get("/api/addresses/countries", response_model=AddressesCountriesResponse)
async def list_addresses_countries(
    search: str = Query(""),
    has_country: str = Query(""),
    country_code: str = Query(""),
    suggested_country: str = Query(""),
    suggest: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    queries: AsyncAddressesQueries = Depends(addresses_queries),
) -> Any:
    """Liste des adresses pour l'attribution de pays."""
    filters = AddressCountriesFilters(
        search=search,
        has_country=has_country,
        country_code=country_code,
        suggested_country=suggested_country,
        suggest=suggest,
    )
    return await queries.addresses_countries(filters=filters, page=page, per_page=per_page)


@router.get("/api/addresses/suggest-countries", response_model=CountrySuggestionsResponse)
async def suggest_countries(
    search: str = Query(""),
    queries: AsyncAddressesQueries = Depends(addresses_queries),
    _: Any = Depends(require_admin),
) -> Any:
    """Distribution des pays des adresses matchantes + compte des sans-pays."""
    return await queries.suggest_countries(search)


@router.post("/api/addresses/{addr_id}/country", response_model=OkResponse)
async def set_address_country(
    addr_id: int,
    body: SetCountry,
    bg: BackgroundTasks,
    conn: AsyncConnection = Depends(db_conn),
    queries: AsyncAddressesQueries = Depends(addresses_queries),
    addr_repo: AsyncAddressRepository = Depends(address_repo),
    _: Any = Depends(require_admin),
) -> Any:
    """Attribue des pays à une adresse."""
    if not await queries.address_exists(addr_id):
        raise HTTPException(status_code=404, detail="Adresse introuvable")
    for c in body.countries or []:
        if not await queries.country_exists(c):
            raise HTTPException(status_code=400, detail=f"Code pays inconnu: {c}")

    affected = await countries_service.set_country(conn, addr_id, body.countries, repo=addr_repo)
    bg.add_task(bg_propagate_countries, affected)
    return {"ok": True}


@router.post("/api/addresses/batch-country", response_model=BatchCountryResponse)
async def batch_set_country(
    body: BatchSetCountry,
    bg: BackgroundTasks,
    conn: AsyncConnection = Depends(db_conn),
    queries: AsyncAddressesQueries = Depends(addresses_queries),
    addr_repo: AsyncAddressRepository = Depends(address_repo),
    _: Any = Depends(require_admin),
) -> Any:
    """Ajoute un pays à des adresses (par IDs ou par filtre)."""
    country_code = body.country_code
    if not country_code:
        raise HTTPException(status_code=400, detail="country_code requis")

    if not await queries.country_exists(country_code):
        raise HTTPException(status_code=400, detail=f"Code pays inconnu: {country_code}")

    if body.address_ids:
        modified_ids = await countries_service.batch_set_country_by_ids(
            conn, country_code, body.address_ids, repo=addr_repo
        )
    else:
        modified_ids = await countries_service.batch_set_country_by_filter(
            conn,
            country_code,
            search=body.search,
            has_country=body.has_country,
            country_code_filter=body.country_code_filter,
            suggested_country=body.suggested_country,
            repo=addr_repo,
        )
    updated = len(modified_ids)

    propagated_ids = await countries_service.propagate_countries_to_similar(conn, repo=addr_repo)
    propagated = len(propagated_ids)
    all_ids = modified_ids + propagated_ids

    bg.add_task(bg_propagate_countries, all_ids)
    return {"updated": updated, "propagated": propagated}


@router.post("/api/addresses/{addr_id}/assign-structure", response_model=AssignStructureResponse)
async def assign_structure(
    addr_id: int,
    action: AssignStructureAction,
    conn: AsyncConnection = Depends(db_conn),
    queries: AsyncAddressesQueries = Depends(addresses_queries),
    addr_repo: AsyncAddressRepository = Depends(address_repo),
    auth_repo: AsyncAuthorshipRepository = Depends(authorship_repo),
    struct_repo: AsyncStructureRepository = Depends(structure_repo),
) -> Any:
    """Assigne manuellement une structure à une adresse."""
    if not await queries.address_exists(addr_id):
        raise HTTPException(status_code=404, detail="Address not found")
    if not await struct_repo.structure_exists(action.structure_id):
        raise HTTPException(status_code=404, detail="Structure not found")

    await structures_service.review_structure_link(
        conn,
        addr_id,
        action.structure_id,
        True,
        repo=addr_repo,
        authorship_repo=auth_repo,
        perimeter_queries=get_perimeter_queries(),
    )
    return {"id": addr_id, "structure_id": action.structure_id, "status": "assigned"}


@router.delete(
    "/api/addresses/{addr_id}/assign-structure", response_model=UnassignStructureResponse
)
async def unassign_structure(
    addr_id: int,
    structure_id: int = Query(...),
    conn: AsyncConnection = Depends(db_conn),
    addr_repo: AsyncAddressRepository = Depends(address_repo),
    auth_repo: AsyncAuthorshipRepository = Depends(authorship_repo),
) -> Any:
    """Supprime l'assignation manuelle d'une structure."""
    deleted = await structures_service.unassign_manual_structure(
        conn,
        addr_id,
        structure_id,
        repo=addr_repo,
        authorship_repo=auth_repo,
        perimeter_queries=get_perimeter_queries(),
    )
    return {"deleted": deleted}


@router.get("/api/admin/address-stats", response_model=AddressStatsResponse)
async def admin_address_stats(
    structure_id: int | None = Query(None),
    queries: AsyncAddressesQueries = Depends(addresses_queries),
) -> Any:
    """Compteurs d'adresses par détection/validation pour une structure."""
    if structure_id is None:
        structure_id = await queries.resolve_default_structure_id()
    return await queries.admin_address_stats(structure_id)
