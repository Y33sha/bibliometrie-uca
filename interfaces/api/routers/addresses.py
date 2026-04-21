"""Router /api/addresses/* et /api/countries.

Les queries sont dans `infrastructure/db/queries/addresses.py`.
Les mutations délèguent à `application.addresses`.
"""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from application import addresses as addresses_service
from infrastructure.app_config import _async_get_from_db
from infrastructure.db.queries import addresses as addr_queries
from infrastructure.db.queries.perimeter import PgAsyncPerimeterQueries
from infrastructure.repositories import async_address_repository, async_authorship_repository
from interfaces.api.async_deps import get_async_cursor
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


async def _bg_propagate_countries(address_ids: list[int]) -> None:
    """Propagation pays en tâche de fond (sur le pool async FastAPI)."""
    try:
        async with get_async_cursor() as (cur, _conn):
            await addresses_service.propagate_countries_to_publications(
                cur, address_ids, repo=async_address_repository(cur)
            )
    except Exception:
        logger.exception("Erreur propagation pays en background")


@router.get("/api/addresses", response_model=AddressListResponse)
async def list_addresses(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    structure_id: int | None = Query(None),
    detected: str = Query("yes"),
    validation: str = Query("pending"),
    search: str = Query(""),
    search_mode: str = Query("contains"),
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

    filters = addr_queries.AddressListFilters(
        detected=detected,
        validation=validation,
        search=search,
        search_mode=search_mode,
    )
    async with get_async_cursor() as (cur, _conn):
        sid = (
            structure_id
            if structure_id is not None
            else await addr_queries.resolve_default_structure_id(cur)
        )
        return await addr_queries.list_addresses(
            cur, structure_id=sid, filters=filters, page=page, per_page=per_page
        )


@router.get("/api/addresses/{addr_id}/publications", response_model=AddressPublicationsResponse)
async def get_address_publications(addr_id: int, limit: int = Query(20)) -> Any:
    """Échantillon de publications liées à une adresse."""
    async with get_async_cursor() as (cur, _conn):
        addr = await addr_queries.get_address_basic(cur, addr_id)
        if not addr:
            raise HTTPException(status_code=404, detail="Address not found")
        publications = await addr_queries.get_address_publications(cur, addr_id, limit)
        return {
            "address_id": addr_id,
            "raw_text": addr["raw_text"],
            "publications": publications,
        }


@router.post("/api/addresses/{addr_id}/review", response_model=AddressReviewResponse)
async def review_address(addr_id: int, action: ReviewAction) -> Any:
    """Confirme, rejette ou reset le lien adresse ↔ structure."""
    async with get_async_cursor() as (cur, _conn):
        await addresses_service.review_structure_link(
            cur,
            addr_id,
            action.structure_id,
            action.is_confirmed,
            repo=async_address_repository(cur),
            authorship_repo=async_authorship_repository(cur),
            perimeter_queries=PgAsyncPerimeterQueries(),
        )
        structures = await addr_queries.get_address_structures(cur, addr_id)
        link = await addr_queries.get_structure_link(cur, addr_id, action.structure_id)
        return {
            "id": addr_id,
            "is_confirmed": link["is_confirmed"] if link else None,
            "is_detected": link["is_detected"] if link else False,
            "structures": structures,
        }


@router.post("/api/addresses/batch-review", response_model=BatchUpdatedResponse)
async def batch_review(data: BatchReviewAction) -> Any:
    """Confirme/rejette/reset en batch."""
    async with get_async_cursor() as (cur, _conn):
        updated = await addresses_service.batch_review_structure_link(
            cur,
            data.address_ids,
            data.structure_id,
            data.is_confirmed,
            repo=async_address_repository(cur),
            authorship_repo=async_authorship_repository(cur),
            perimeter_queries=PgAsyncPerimeterQueries(),
        )
        return {"updated": updated}


@router.get("/api/countries", response_model=list[CountryOut])
async def list_countries() -> Any:
    """Liste des pays."""
    async with get_async_cursor() as (cur, _conn):
        return await addr_queries.list_countries(cur)


@router.get("/api/addresses/countries", response_model=AddressesCountriesResponse)
async def addresses_countries(
    search: str = Query(""),
    has_country: str = Query(""),
    country_code: str = Query(""),
    suggested_country: str = Query(""),
    suggest: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Liste des adresses pour l'attribution de pays."""
    filters = addr_queries.AddressCountriesFilters(
        search=search,
        has_country=has_country,
        country_code=country_code,
        suggested_country=suggested_country,
        suggest=suggest,
    )
    async with get_async_cursor() as (cur, _conn):
        return await addr_queries.addresses_countries(
            cur, filters=filters, page=page, per_page=per_page
        )


@router.get("/api/addresses/suggest-countries", response_model=CountrySuggestionsResponse)
async def suggest_countries(
    search: str = Query(""),
    _: Any = Depends(require_admin),
) -> Any:
    """Distribution des pays des adresses matchantes + compte des sans-pays."""
    async with get_async_cursor() as (cur, _conn):
        return await addr_queries.suggest_countries(cur, search)


@router.post("/api/addresses/{addr_id}/country", response_model=OkResponse)
async def set_address_country(
    addr_id: int, body: SetCountry, bg: BackgroundTasks, _: Any = Depends(require_admin)
) -> Any:
    """Attribue des pays à une adresse."""
    async with get_async_cursor() as (cur, _conn):
        if not await addr_queries.address_exists(cur, addr_id):
            raise HTTPException(status_code=404, detail="Adresse introuvable")
        for c in body.countries or []:
            if not await addr_queries.country_exists(cur, c):
                raise HTTPException(status_code=400, detail=f"Code pays inconnu: {c}")
        affected = await addresses_service.set_country(
            cur, addr_id, body.countries, repo=async_address_repository(cur)
        )
    bg.add_task(_bg_propagate_countries, affected)
    return {"ok": True}


@router.post("/api/addresses/batch-country", response_model=BatchCountryResponse)
async def batch_set_country(
    body: BatchSetCountry, bg: BackgroundTasks, _: Any = Depends(require_admin)
) -> Any:
    """Ajoute un pays à des adresses (par IDs ou par filtre)."""
    country_code = body.country_code
    if not country_code:
        raise HTTPException(status_code=400, detail="country_code requis")

    async with get_async_cursor() as (cur, _conn):
        if not await addr_queries.country_exists(cur, country_code):
            raise HTTPException(status_code=400, detail=f"Code pays inconnu: {country_code}")

        addr_repo = async_address_repository(cur)
        if body.address_ids:
            modified_ids = await addresses_service.batch_set_country_by_ids(
                cur, country_code, body.address_ids, repo=addr_repo
            )
        else:
            modified_ids = await addresses_service.batch_set_country_by_filter(
                cur,
                country_code,
                search=body.search,
                has_country=body.has_country,
                country_code_filter=body.country_code_filter,
                suggested_country=body.suggested_country,
                repo=addr_repo,
            )
        updated = len(modified_ids)

        propagated_ids = await addresses_service.propagate_countries_to_similar(
            cur, repo=addr_repo
        )
        propagated = len(propagated_ids)
        all_ids = modified_ids + propagated_ids

    bg.add_task(_bg_propagate_countries, all_ids)
    return {"updated": updated, "propagated": propagated}


@router.post("/api/addresses/{addr_id}/assign-structure", response_model=AssignStructureResponse)
async def assign_structure(addr_id: int, action: AssignStructureAction) -> Any:
    """Assigne manuellement une structure à une adresse."""
    async with get_async_cursor() as (cur, _conn):
        await cur.execute("SELECT id FROM addresses WHERE id = %s", (addr_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Address not found")

        await cur.execute("SELECT id FROM structures WHERE id = %s", (action.structure_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Structure not found")

        await addresses_service.review_structure_link(
            cur,
            addr_id,
            action.structure_id,
            True,
            repo=async_address_repository(cur),
            authorship_repo=async_authorship_repository(cur),
            perimeter_queries=PgAsyncPerimeterQueries(),
        )
        return {"id": addr_id, "structure_id": action.structure_id, "status": "assigned"}


@router.delete(
    "/api/addresses/{addr_id}/assign-structure", response_model=UnassignStructureResponse
)
async def unassign_structure(addr_id: int, structure_id: int = Query(...)) -> Any:
    """Supprime l'assignation manuelle d'une structure."""
    async with get_async_cursor() as (cur, _conn):
        deleted = await addresses_service.unassign_manual_structure(
            cur,
            addr_id,
            structure_id,
            repo=async_address_repository(cur),
            authorship_repo=async_authorship_repository(cur),
            perimeter_queries=PgAsyncPerimeterQueries(),
        )
        return {"deleted": deleted}


@router.get("/api/admin/address-stats", response_model=AddressStatsResponse)
async def admin_address_stats(structure_id: int | None = Query(None)) -> Any:
    """Compteurs d'adresses par détection/validation pour une structure."""
    async with get_async_cursor() as (cur, _conn):
        # Résoudre la structure (défaut = première racine du périmètre)
        if structure_id is None:
            perim_code = await _async_get_from_db(cur, "perimeter_persons") or "uca"
            await cur.execute(
                "SELECT structure_ids FROM perimeters WHERE code = %s", (perim_code,)
            )
            row = await cur.fetchone()
            root_ids = (row["structure_ids"] if isinstance(row, dict) else row[0]) if row else []
            structure_id = root_ids[0] if root_ids else 0

        await cur.execute("SELECT COUNT(*) AS total FROM addresses")
        total = (await cur.fetchone())["total"]

        await cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE ast.matched_form_id IS NOT NULL) AS detected,
                COUNT(*) FILTER (WHERE ast.is_confirmed IS NULL) AS pending,
                COUNT(*) FILTER (WHERE ast.is_confirmed = FALSE) AS rejected,
                COUNT(*) FILTER (WHERE ast.is_confirmed = TRUE) AS confirmed
            FROM address_structures ast
            WHERE ast.structure_id = %s
            """,
            (structure_id,),
        )
        row = await cur.fetchone()

        return {
            "total": total,
            "detected": row["detected"],
            "pending": row["pending"],
            "rejected": row["rejected"],
            "confirmed": row["confirmed"],
        }
