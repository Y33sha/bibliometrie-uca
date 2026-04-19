"""Router /api/authorships/* — délègue à infrastructure/db/queries/authorships.py."""

import logging
from typing import Any

from fastapi import APIRouter, Query

from infrastructure.db.queries import authorships as auth_queries
from interfaces.api.deps import get_cursor

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/authorships/stats")
async def authorships_stats(lab_id: int = Query(0)) -> Any:
    """Statistiques auteurs UCA."""
    with get_cursor() as (cur, _conn):
        return auth_queries.authorships_stats(cur, lab_id)


@router.get("/api/authorships/facets")
async def authorships_facets(
    linked: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    lab_id: int = Query(0),
) -> Any:
    """Facettes dynamiques pour la page authorships admin."""
    with get_cursor() as (cur, _conn):
        return auth_queries.authorships_facets(
            cur, linked=linked, has_orcid=has_orcid, has_idhal=has_idhal, lab_id=lab_id
        )


@router.get("/api/authorships")
async def list_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    linked: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    lab_id: int = Query(0),
) -> Any:
    """Liste des auteurs UCA avec filtres."""
    with get_cursor() as (cur, _conn):
        return auth_queries.list_authorships(
            cur,
            search=search,
            linked=linked,
            has_orcid=has_orcid,
            has_idhal=has_idhal,
            lab_id=lab_id,
            page=page,
            per_page=per_page,
        )
