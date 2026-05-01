"""Router Revues — liste, recherche, fusion."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.journals import merge_journals
from application.journals import update_journal as _update_journal
from infrastructure.db.queries.journals import (
    existing_journal_ids,
    get_journal_async,
    list_journals_async,
)
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
    async with get_async_cursor() as (cur, _conn):
        return await list_journals_async(
            cur,
            search=search,
            publisher_id=publisher_id,
            sort=sort,
            page=page,
            per_page=per_page,
        )


@router.get("/api/journals/{journal_id}")
async def get_journal(journal_id: int) -> Any:
    """Récupère une revue par son id (titre uniquement). 404 si inconnue."""
    async with get_async_cursor() as (cur, _conn):
        row = await get_journal_async(cur, journal_id)
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
    async with get_async_cursor() as (cur, _conn):
        await _update_journal(cur, journal_id, fields=fields, repo=async_journal_repository(cur))
        return {"ok": True}


@router.post("/api/journals/{journal_id}/merge")
async def merge(journal_id: int, body: MergeRequest) -> Any:
    """Fusionne la revue `source_id` dans la revue `journal_id`.

    Les publications et métadonnées de la source sont transférées à
    la cible ; la source est supprimée. 404 si l'une des deux est
    introuvable.
    """
    async with get_async_cursor() as (cur, _conn):
        found = await existing_journal_ids(cur, (journal_id, body.source_id))
        if journal_id not in found:
            raise HTTPException(status_code=404, detail="Revue cible introuvable")
        if body.source_id not in found:
            raise HTTPException(status_code=404, detail="Revue source introuvable")

        await merge_journals(cur, journal_id, body.source_id, repo=async_journal_repository(cur))
        return {"merged": True, "source_id": body.source_id, "target_id": journal_id}
