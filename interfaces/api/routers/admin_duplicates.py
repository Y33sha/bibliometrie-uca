"""Router /api/admin/duplicates/* (doublons publications)."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.publications import mark_distinct as _mark_pubs_distinct
from application.publications import merge_publications
from infrastructure.db.queries import duplicates as dup_queries
from infrastructure.repositories import publication_repository
from interfaces.api.deps import get_cursor
from interfaces.api.models import (
    MarkDistinctPublications,
    MergePublications,
    OkResponse,
    PubDuplicateNextResponse,
    PubMergeResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/duplicates/next", response_model=PubDuplicateNextResponse)
async def next_duplicate_candidate(
    min_title_len: int = Query(30, ge=10),
    offset: int = Query(0, ge=0),
) -> Any:
    """Renvoie la paire candidate à la position offset."""
    with get_cursor() as (cur, _conn):
        return dup_queries.next_pub_duplicate(cur, min_title_len=min_title_len, offset=offset)


@router.post("/api/admin/duplicates/merge", response_model=PubMergeResponse)
async def merge_duplicate_publications(body: MergePublications) -> Any:
    """Fusionne source_id dans target_id."""
    if body.target_id == body.source_id:
        raise HTTPException(
            status_code=400, detail="target_id et source_id doivent être différents"
        )

    with get_cursor() as (cur, _conn):
        pubs = dup_queries.get_publications_basic(cur, [body.target_id, body.source_id])
        if body.target_id not in pubs or body.source_id not in pubs:
            raise HTTPException(status_code=404, detail="Publication introuvable")

        cur.execute("SAVEPOINT merge_dup")
        try:
            merge_publications(
                cur, body.target_id, body.source_id, repo=publication_repository(cur)
            )
            cur.execute("RELEASE SAVEPOINT merge_dup")
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT merge_dup")
            raise HTTPException(status_code=500, detail=f"Échec de la fusion : {e}") from e

        return {"ok": True, "target_id": body.target_id, "source_id": body.source_id}


@router.post("/api/admin/duplicates/mark-distinct", response_model=OkResponse)
async def mark_publications_distinct(body: MarkDistinctPublications) -> Any:
    """Marque deux publications comme distinctes (non-doublon)."""
    if body.pub_id_a == body.pub_id_b:
        raise HTTPException(status_code=400, detail="pub_id_a et pub_id_b doivent être différents")
    with get_cursor() as (cur, _conn):
        _mark_pubs_distinct(cur, body.pub_id_a, body.pub_id_b, repo=publication_repository(cur))
        return {"ok": True}
