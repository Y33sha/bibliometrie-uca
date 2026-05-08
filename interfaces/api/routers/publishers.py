"""Router Éditeurs — liste, recherche, fusion."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from application.ports.publishers_queries import AsyncPublisherQueries
from application.publishers import merge_publishers
from application.publishers import update_publisher as _update_publisher
from domain.ports.audit_repository import AsyncAuditRepository
from domain.ports.journal_repository import AsyncJournalRepository
from domain.ports.publisher_repository import AsyncPublisherRepository
from interfaces.api.async_deps import (
    audit_repo,
    db_conn,
    journal_repo,
    publisher_queries,
    publisher_repo,
)
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
    queries: AsyncPublisherQueries = Depends(publisher_queries),
) -> Any:
    """Liste paginée des éditeurs avec comptage revues + publications.

    `search` : recherche sur le nom normalisé, ignorée si < 2
    caractères. `sort` : `name` / `-name` / `journals` / `-journals`
    / `pubs` / `-pubs` ; fallback sur `name` si inconnu.
    """
    return await queries.list_publishers(search=search, sort=sort, page=page, per_page=per_page)


@router.get("/api/publishers/{publisher_id}", response_model=PublisherBasic)
async def get_publisher(
    publisher_id: int,
    queries: AsyncPublisherQueries = Depends(publisher_queries),
) -> Any:
    """Récupère un éditeur par son id (nom uniquement). 404 si inconnu."""
    row = await queries.get_publisher(publisher_id)
    if not row:
        raise HTTPException(status_code=404, detail="Éditeur introuvable")
    return row


@router.put("/api/publishers/{publisher_id}", response_model=OkResponse)
async def update_publisher(
    publisher_id: int,
    body: PublisherUpdate,
    conn: AsyncConnection = Depends(db_conn),
    repo: AsyncPublisherRepository = Depends(publisher_repo),
) -> Any:
    """Met à jour un éditeur (modification sélective des champs fournis).

    Seuls les champs explicitement présents dans le body sont écrits
    (`exclude_unset=True`). Lève 404 si l'éditeur n'existe pas.
    """
    fields = body.model_dump(exclude_unset=True)
    await _update_publisher(conn, publisher_id, fields=fields, repo=repo)
    return {"ok": True}


@router.post("/api/publishers/{publisher_id}/merge", response_model=MergeResponse)
async def merge(
    publisher_id: int,
    body: MergeRequest,
    conn: AsyncConnection = Depends(db_conn),
    queries: AsyncPublisherQueries = Depends(publisher_queries),
    pub_repo: AsyncPublisherRepository = Depends(publisher_repo),
    j_repo: AsyncJournalRepository = Depends(journal_repo),
    audit: AsyncAuditRepository = Depends(audit_repo),
) -> Any:
    """Fusionne l'éditeur `source_id` dans l'éditeur `publisher_id`.

    Les revues et publications rattachées à la source sont
    transférées à la cible ; la source est supprimée. 404 si l'un
    des deux éditeurs est introuvable.
    """
    found = await queries.existing_publisher_ids((publisher_id, body.source_id))
    if publisher_id not in found:
        raise HTTPException(status_code=404, detail="Éditeur cible introuvable")
    if body.source_id not in found:
        raise HTTPException(status_code=404, detail="Éditeur source introuvable")

    await merge_publishers(
        conn,
        publisher_id,
        body.source_id,
        publisher_repo=pub_repo,
        journal_repo=j_repo,
        audit_repo=audit,
    )
    return {"merged": True, "source_id": body.source_id, "target_id": publisher_id}
