"""Router Éditeurs — liste, recherche, fusion."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.journals import merge_publishers
from application.journals import update_publisher as _update_publisher
from infrastructure.repositories import async_journal_repository
from interfaces.api.async_deps import get_async_cursor
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
    async with get_async_cursor() as (cur, conn):
        conditions = []
        params = []

        if search and len(search) >= 2:
            conditions.append("p.name_normalized LIKE '%%' || %s || '%%'")
            params.append(search.lower())

        where = " AND ".join(conditions) if conditions else "TRUE"

        # Count
        await cur.execute(f"SELECT COUNT(*) FROM publishers p WHERE {where}", params)
        total = (await cur.fetchone())["count"]

        # Sort
        sort_map = {
            "name": "p.name ASC",
            "-name": "p.name DESC",
            "journals": "journal_count ASC, p.name ASC",
            "-journals": "journal_count DESC, p.name ASC",
            "pubs": "pub_count ASC, p.name ASC",
            "-pubs": "pub_count DESC, p.name ASC",
        }
        order = sort_map.get(sort, sort_map["name"])

        offset = (page - 1) * per_page
        await cur.execute(
            f"""
            SELECT p.id, p.name, p.openalex_id, p.country,
                   p.doi_prefix, p.is_predatory,
                   (SELECT COUNT(*) FROM journals j WHERE j.publisher_id = p.id) AS journal_count,
                   (SELECT COUNT(*) FROM publications pub
                    JOIN journals j2 ON j2.id = pub.journal_id
                    WHERE j2.publisher_id = p.id) AS pub_count
            FROM publishers p
            WHERE {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )

        return {
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "publishers": await cur.fetchall(),
        }


@router.get("/api/publishers/{publisher_id}", response_model=PublisherBasic)
async def get_publisher(publisher_id: int) -> Any:
    """Récupère un éditeur par son id (nom uniquement). 404 si inconnu."""
    async with get_async_cursor() as (cur, conn):
        await cur.execute("SELECT id, name FROM publishers WHERE id = %s", (publisher_id,))
        row = await cur.fetchone()
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
    async with get_async_cursor() as (cur, conn):
        await _update_publisher(
            cur, publisher_id, fields=fields, repo=async_journal_repository(cur)
        )
        return {"ok": True}


@router.post("/api/publishers/{publisher_id}/merge", response_model=MergeResponse)
async def merge(publisher_id: int, body: MergeRequest) -> Any:
    """Fusionne l'éditeur `source_id` dans l'éditeur `publisher_id`.

    Les revues et publications rattachées à la source sont
    transférées à la cible ; la source est supprimée. 404 si l'un
    des deux éditeurs est introuvable.
    """
    async with get_async_cursor() as (cur, conn):
        await cur.execute(
            "SELECT id FROM publishers WHERE id IN (%s, %s)", (publisher_id, body.source_id)
        )
        found = {row["id"] for row in await cur.fetchall()}
        if publisher_id not in found:
            raise HTTPException(status_code=404, detail="Éditeur cible introuvable")
        if body.source_id not in found:
            raise HTTPException(status_code=404, detail="Éditeur source introuvable")

        await merge_publishers(
            cur, publisher_id, body.source_id, repo=async_journal_repository(cur)
        )
        return {"merged": True, "source_id": body.source_id, "target_id": publisher_id}
