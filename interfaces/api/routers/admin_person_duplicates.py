"""Router /api/admin/person-duplicates/*."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.persons import mark_distinct as _mark_persons_distinct
from infrastructure.db.queries import person_duplicates as dup_queries
from infrastructure.repositories import async_person_repository
from interfaces.api.async_deps import get_async_cursor
from interfaces.api.models import (
    MarkPersonsDistinct,
    OkResponse,
    PersonConflictPairResponse,
    PersonDuplicatePairResponse,
    TotalCountResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/person-duplicates/count", response_model=TotalCountResponse)
async def count_person_duplicates() -> Any:
    """Comptage des paires candidates doublons-personnes."""
    async with get_async_cursor() as (cur, _conn):
        return {"total": await dup_queries.count_person_duplicates(cur)}


@router.get("/api/admin/person-duplicates/next", response_model=PersonDuplicatePairResponse)
async def next_person_duplicate(
    skip: str = Query("", alias="skip"),
    offset: int = Query(0, ge=0),
) -> Any:
    """Renvoie la paire personne-candidate au dédoublonnage à l'offset donné.

    `skip` : liste CSV de paires `idA-idB` à ignorer pour cette
    session (défilement côté front sans revoir les mêmes candidats).
    Renvoie `{"pair": null}` si aucune paire restante.
    """
    skip_pairs = dup_queries.parse_skip_pairs(skip) if skip else None
    async with get_async_cursor() as (cur, _conn):
        pair = await dup_queries.next_person_duplicate(cur, skip_pairs=skip_pairs, offset=offset)
        return {"pair": pair}


@router.post("/api/admin/person-duplicates/mark-distinct", response_model=OkResponse)
async def mark_persons_distinct(body: MarkPersonsDistinct) -> Any:
    """Marque deux personnes comme distinctes (non-doublon)."""
    if body.person_id_a == body.person_id_b:
        raise HTTPException(
            status_code=400, detail="person_id_a et person_id_b doivent être différents"
        )
    async with get_async_cursor() as (cur, _conn):
        await _mark_persons_distinct(
            cur, body.person_id_a, body.person_id_b, repo=async_person_repository(cur)
        )
        return {"ok": True}


@router.get("/api/admin/person-duplicates/conflicts/count", response_model=TotalCountResponse)
async def count_person_conflict_pairs() -> Any:
    """Nombre de paires de personnes co-auteurs d'une même publication.

    Un conflit = deux `person_id` distincts rattachés à la même
    `publication_id` alors que leur forme de nom est compatible →
    suggère un doublon que la déduplication classique n'a pas vu.
    """
    async with get_async_cursor() as (cur, _conn):
        return {"total": await dup_queries.count_person_conflict_pairs(cur)}


@router.get(
    "/api/admin/person-duplicates/conflicts/next", response_model=PersonConflictPairResponse
)
async def next_person_conflict(
    skip: str = Query("", alias="skip"),
    offset: int = Query(0, ge=0),
) -> Any:
    """Renvoie la paire personnes-en-conflit à l'offset donné.

    Même protocole que `/person-duplicates/next` (paire + skip +
    offset) mais pour les conflits co-auteurs plutôt que les
    candidats de similarité de nom.
    """
    skip_pairs = dup_queries.parse_skip_pairs(skip) if skip else set()
    async with get_async_cursor() as (cur, conn):
        pair = await dup_queries.next_person_conflict(
            cur, conn, skip_pairs=skip_pairs, offset=offset
        )
        return {"pair": pair}
