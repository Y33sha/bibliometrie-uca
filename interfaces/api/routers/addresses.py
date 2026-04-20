"""Router /api/addresses/* et /api/countries.

Les queries sont dans `infrastructure/db/queries/addresses.py`.
Les mutations délèguent à `application.addresses`.
"""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from application import addresses as addresses_service
from infrastructure.db.queries import addresses as addr_queries
from infrastructure.repositories import authorship_repository
from interfaces.api.deps import get_cursor, require_admin
from interfaces.api.models import (
    BatchReviewAction,
    BatchSetCountry,
    ReviewAction,
    SetCountry,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _bg_propagate_countries(address_ids: list[int]) -> None:
    """Propagation pays en tâche de fond (connexion séparée)."""
    from infrastructure.db.connection import get_connection

    try:
        conn = get_connection()
        cur = conn.cursor()
        addresses_service.propagate_countries_to_publications(cur, address_ids)
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        logger.exception("Erreur propagation pays en background")


@router.get("/api/addresses")
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
    with get_cursor() as (cur, _conn):
        sid = (
            structure_id
            if structure_id is not None
            else addr_queries.resolve_default_structure_id(cur)
        )
        return addr_queries.list_addresses(
            cur, structure_id=sid, filters=filters, page=page, per_page=per_page
        )


@router.get("/api/addresses/{addr_id}/publications")
async def get_address_publications(addr_id: int, limit: int = Query(20)) -> Any:
    """Échantillon de publications liées à une adresse."""
    with get_cursor() as (cur, _conn):
        addr = addr_queries.get_address_basic(cur, addr_id)
        if not addr:
            raise HTTPException(status_code=404, detail="Address not found")
        publications = addr_queries.get_address_publications(cur, addr_id, limit)
        return {
            "address_id": addr_id,
            "raw_text": addr["raw_text"],
            "publications": publications,
        }


@router.post("/api/addresses/{addr_id}/review")
async def review_address(addr_id: int, action: ReviewAction) -> Any:
    """Confirme, rejette ou reset le lien adresse ↔ structure."""
    with get_cursor() as (cur, _conn):
        addresses_service.review_structure_link(
            cur,
            addr_id,
            action.structure_id,
            action.is_confirmed,
            authorship_repo=authorship_repository(cur),
        )
        structures = addr_queries.get_address_structures(cur, addr_id)
        link = addr_queries.get_structure_link(cur, addr_id, action.structure_id)
        return {
            "id": addr_id,
            "is_confirmed": link["is_confirmed"] if link else None,
            "is_detected": link["is_detected"] if link else False,
            "structures": structures,
        }


@router.post("/api/addresses/batch-review")
async def batch_review(data: BatchReviewAction) -> Any:
    """Confirme/rejette/reset en batch."""
    with get_cursor() as (cur, _conn):
        updated = addresses_service.batch_review_structure_link(
            cur,
            data.address_ids,
            data.structure_id,
            data.is_confirmed,
            authorship_repo=authorship_repository(cur),
        )
        return {"updated": updated}


@router.get("/api/countries")
async def list_countries() -> Any:
    """Liste des pays."""
    with get_cursor() as (cur, _conn):
        return addr_queries.list_countries(cur)


@router.get("/api/addresses/countries")
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
    with get_cursor() as (cur, _conn):
        return addr_queries.addresses_countries(cur, filters=filters, page=page, per_page=per_page)


@router.get("/api/addresses/suggest-countries")
async def suggest_countries(
    search: str = Query(""),
    _: Any = Depends(require_admin),
) -> Any:
    """Distribution des pays des adresses matchantes + compte des sans-pays."""
    with get_cursor() as (cur, _conn):
        return addr_queries.suggest_countries(cur, search)


@router.post("/api/addresses/{addr_id}/country")
async def set_address_country(
    addr_id: int, body: SetCountry, bg: BackgroundTasks, _: Any = Depends(require_admin)
) -> Any:
    """Attribue des pays à une adresse."""
    with get_cursor() as (cur, _conn):
        if not addr_queries.address_exists(cur, addr_id):
            raise HTTPException(status_code=404, detail="Adresse introuvable")
        for c in body.countries or []:
            if not addr_queries.country_exists(cur, c):
                raise HTTPException(status_code=400, detail=f"Code pays inconnu: {c}")
        affected = addresses_service.set_country(cur, addr_id, body.countries)
    bg.add_task(_bg_propagate_countries, affected)
    return {"ok": True}


@router.post("/api/addresses/batch-country")
async def batch_set_country(
    body: BatchSetCountry, bg: BackgroundTasks, _: Any = Depends(require_admin)
) -> Any:
    """Ajoute un pays à des adresses (par IDs ou par filtre)."""
    country_code = body.country_code
    if not country_code:
        raise HTTPException(status_code=400, detail="country_code requis")

    with get_cursor() as (cur, _conn):
        if not addr_queries.country_exists(cur, country_code):
            raise HTTPException(status_code=400, detail=f"Code pays inconnu: {country_code}")

        if body.address_ids:
            modified_ids = addresses_service.batch_set_country_by_ids(
                cur, country_code, body.address_ids
            )
        else:
            modified_ids = addresses_service.batch_set_country_by_filter(
                cur,
                country_code,
                search=body.search,
                has_country=body.has_country,
                country_code_filter=body.country_code_filter,
                suggested_country=body.suggested_country,
            )
        updated = len(modified_ids)

        propagated_ids = addresses_service.propagate_countries_to_similar(cur)
        propagated = len(propagated_ids)
        all_ids = modified_ids + propagated_ids

    bg.add_task(_bg_propagate_countries, all_ids)
    return {"updated": updated, "propagated": propagated}
