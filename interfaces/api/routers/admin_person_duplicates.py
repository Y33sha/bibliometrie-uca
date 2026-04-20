"""Router /api/admin/person-duplicates/*."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.persons import mark_distinct as _mark_persons_distinct
from infrastructure.db.queries import duplicates as dup_queries
from infrastructure.repositories import person_repository
from interfaces.api.deps import get_cursor
from interfaces.api.models import MarkPersonsDistinct

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/person-duplicates/count")
async def count_person_duplicates() -> Any:
    """Comptage des paires candidates doublons-personnes."""
    with get_cursor() as (cur, _conn):
        return {"total": dup_queries.count_person_duplicates(cur)}


@router.get("/api/admin/person-duplicates/next")
async def next_person_duplicate(
    skip: str = Query("", alias="skip"),
    offset: int = Query(0, ge=0),
) -> Any:
    """Renvoie la paire doublon-personne à la position offset."""
    skip_pairs = dup_queries.parse_skip_pairs(skip) if skip else None
    with get_cursor() as (cur, _conn):
        pair = dup_queries.next_person_duplicate(cur, skip_pairs=skip_pairs, offset=offset)
        return {"pair": pair}


@router.post("/api/admin/person-duplicates/mark-distinct")
async def mark_persons_distinct(body: MarkPersonsDistinct) -> Any:
    """Marque deux personnes comme distinctes (non-doublon)."""
    if body.person_id_a == body.person_id_b:
        raise HTTPException(
            status_code=400, detail="person_id_a et person_id_b doivent être différents"
        )
    with get_cursor() as (cur, _conn):
        _mark_persons_distinct(
            cur, body.person_id_a, body.person_id_b, repo=person_repository(cur)
        )
        return {"ok": True}


@router.get("/api/admin/person-duplicates/conflicts/count")
async def count_person_conflict_pairs() -> Any:
    """Nombre de paires de personnes en conflit sur des publications."""
    with get_cursor() as (cur, _conn):
        return {"total": dup_queries.count_person_conflict_pairs(cur)}


@router.get("/api/admin/person-duplicates/conflicts/next")
async def next_person_conflict(
    skip: str = Query("", alias="skip"),
    offset: int = Query(0, ge=0),
) -> Any:
    """Renvoie la paire en conflit à la position offset."""
    skip_pairs = dup_queries.parse_skip_pairs(skip) if skip else set()
    with get_cursor() as (cur, conn):
        pair = dup_queries.next_person_conflict(cur, conn, skip_pairs=skip_pairs, offset=offset)
        return {"pair": pair}
