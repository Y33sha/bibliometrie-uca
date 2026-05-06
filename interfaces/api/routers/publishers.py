"""Router Éditeurs — liste, recherche, fusion."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.publishers import merge_publishers
from application.publishers import update_publisher as _update_publisher
from infrastructure.db.queries.publishers import (
    existing_publisher_ids,
    get_publisher_async,
    list_publishers_async,
)
from infrastructure.repositories import async_journal_repository, async_publisher_repository
from interfaces.api.async_deps import get_async_cursor, get_sa_connection
from interfaces.api.models import (
    MergeRequest,
    MergeResponse,
    OkResponse,
    PublisherBasic,
    PublisherListResponse,
    PublisherUpdate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/publishers", response_model=PublisherListResponse)
async def list_publishers(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    sort: str = "name",
) -> Any:
    """Liste paginée des éditeurs avec comptage revues + publications.

    `search` : recherche sur le nom normalisé, ignorée si < 2
    caractères. `sort` : `name` / `-name` / `journals` / `-journals`
    / `pubs` / `-pubs` ; fallback sur `name` si inconnu.
    """
    async with get_async_cursor() as (cur, _conn):
        return await list_publishers_async(
            cur, search=search, sort=sort, page=page, per_page=per_page
        )


@router.get("/api/publishers/{publisher_id}", response_model=PublisherBasic)
async def get_publisher(publisher_id: int) -> Any:
    """Récupère un éditeur par son id (nom uniquement). 404 si inconnu."""
    async with get_async_cursor() as (cur, _conn):
        row = await get_publisher_async(cur, publisher_id)
        if not row:
            raise HTTPException(status_code=404, detail="Éditeur introuvable")
        return row


@router.put("/api/publishers/{publisher_id}", response_model=OkResponse)
async def update_publisher(publisher_id: int, body: PublisherUpdate) -> Any:
    """Met à jour un éditeur (modification sélective des champs fournis).

    Seuls les champs explicitement présents dans le body sont écrits
    (`exclude_unset=True`). Lève 404 si l'éditeur n'existe pas.
    """
    fields = body.model_dump(exclude_unset=True)
    async with get_sa_connection() as conn:
        await _update_publisher(
            conn, publisher_id, fields=fields, repo=async_publisher_repository(conn)
        )
        return {"ok": True}


@router.post("/api/publishers/{publisher_id}/merge", response_model=MergeResponse)
async def merge(publisher_id: int, body: MergeRequest) -> Any:
    """Fusionne l'éditeur `source_id` dans l'éditeur `publisher_id`.

    Les revues et publications rattachées à la source sont
    transférées à la cible ; la source est supprimée. 404 si l'un
    des deux éditeurs est introuvable.
    """
    async with get_sa_connection() as conn:
        found = await existing_publisher_ids(conn, (publisher_id, body.source_id))
        if publisher_id not in found:
            raise HTTPException(status_code=404, detail="Éditeur cible introuvable")
        if body.source_id not in found:
            raise HTTPException(status_code=404, detail="Éditeur source introuvable")

        await merge_publishers(
            conn,
            publisher_id,
            body.source_id,
            publisher_repo=async_publisher_repository(conn),
            journal_repo=async_journal_repository(conn),
        )
        return {"merged": True, "source_id": body.source_id, "target_id": publisher_id}
