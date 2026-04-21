"""Router Revues — liste, recherche, fusion."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.journals import merge_journals
from application.journals import update_journal as _update_journal
from infrastructure.repositories import async_journal_repository
from interfaces.api.async_deps import get_async_cursor
from interfaces.api.models import JournalListResponse, JournalUpdate, MergeRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/journals", response_model=JournalListResponse)
async def list_journals(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = None,
    publisher_id: int | None = None,
    sort: str = "title",
) -> Any:
    """Liste paginée des revues avec comptage des publications rattachées.

    `search` : recherche insensible à la casse sur le titre normalisé,
    ignorée si < 2 caractères. `publisher_id` : filtre par éditeur.
    `sort` : `title` / `-title` / `publisher` / `-publisher` /
    `pubs` / `-pubs` ; fallback sur `title` si valeur inconnue.
    """
    async with get_async_cursor() as (cur, conn):
        conditions = []
        params: list[Any] = []

        if search and len(search) >= 2:
            conditions.append("j.title_normalized LIKE '%%' || %s || '%%'")
            params.append(search.lower())

        if publisher_id:
            conditions.append("j.publisher_id = %s")
            params.append(publisher_id)

        where = " AND ".join(conditions) if conditions else "TRUE"

        # Count
        await cur.execute(f"SELECT COUNT(*) FROM journals j WHERE {where}", params)
        total = (await cur.fetchone())["count"]

        # Sort
        sort_map = {
            "title": "j.title ASC",
            "-title": "j.title DESC",
            "publisher": "pub_name ASC NULLS LAST, j.title ASC",
            "-publisher": "pub_name DESC NULLS LAST, j.title ASC",
            "pubs": "pub_count ASC, j.title ASC",
            "-pubs": "pub_count DESC, j.title ASC",
        }
        order = sort_map.get(sort, sort_map["title"])

        offset = (page - 1) * per_page
        await cur.execute(
            f"""
            SELECT j.id, j.title, j.issn, j.eissn, j.issnl,
                   j.publisher_id, p.name AS pub_name,
                   j.openalex_id, j.is_in_doaj, j.is_predatory,
                   j.apc_amount, j.apc_currency, j.oa_model,
                   j.journal_type, j.is_academic, j.doi_prefix, j.notes,
                   (SELECT COUNT(*) FROM publications pub
                    WHERE pub.journal_id = j.id) AS pub_count
            FROM journals j
            LEFT JOIN publishers p ON p.id = j.publisher_id
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
            "journals": await cur.fetchall(),
        }


@router.get("/api/journals/{journal_id}")
async def get_journal(journal_id: int) -> Any:
    """Récupère une revue par son id (titre uniquement). 404 si inconnue."""
    async with get_async_cursor() as (cur, conn):
        await cur.execute("SELECT id, title FROM journals WHERE id = %s", (journal_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Revue introuvable")
        return row


@router.put("/api/journals/{journal_id}")
async def update_journal(journal_id: int, body: JournalUpdate) -> Any:
    """Met à jour une revue (modification sélective des champs fournis).

    Seuls les champs explicitement présents dans le body sont écrits
    (`exclude_unset=True`). Lève 404 si la revue n'existe pas.
    """
    fields = body.model_dump(exclude_unset=True)
    async with get_async_cursor() as (cur, conn):
        await _update_journal(cur, journal_id, fields=fields, repo=async_journal_repository(cur))
        return {"ok": True}


@router.post("/api/journals/{journal_id}/merge")
async def merge(journal_id: int, body: MergeRequest) -> Any:
    """Fusionne la revue `source_id` dans la revue `journal_id`.

    Les publications et métadonnées de la source sont transférées à
    la cible ; la source est supprimée. 404 si l'une des deux est
    introuvable.
    """
    async with get_async_cursor() as (cur, conn):
        await cur.execute(
            "SELECT id FROM journals WHERE id IN (%s, %s)", (journal_id, body.source_id)
        )
        found = {row["id"] for row in await cur.fetchall()}
        if journal_id not in found:
            raise HTTPException(status_code=404, detail="Revue cible introuvable")
        if body.source_id not in found:
            raise HTTPException(status_code=404, detail="Revue source introuvable")

        await merge_journals(
            cur, journal_id, body.source_id, repo=async_journal_repository(cur)
        )
        return {"merged": True, "source_id": body.source_id, "target_id": journal_id}
