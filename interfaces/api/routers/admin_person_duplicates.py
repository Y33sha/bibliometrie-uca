"""Router /api/admin/person-duplicates/*."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from application.persons import mark_distinct as _mark_persons_distinct
from application.ports.person_duplicates_queries import (
    AsyncPersonDuplicatesQueries,
    parse_skip_pairs,
)
from domain.ports.person_repository import AsyncPersonRepository
from interfaces.api.async_deps import (
    db_conn,
    person_duplicates_queries,
    person_repo,
)
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
async def count_person_duplicates(
    queries: AsyncPersonDuplicatesQueries = Depends(person_duplicates_queries),
) -> Any:
    """Comptage des paires candidates doublons-personnes."""
    return {"total": await queries.count_person_duplicates()}


@router.get("/api/admin/person-duplicates/next", response_model=PersonDuplicatePairResponse)
async def next_person_duplicate(
    skip: str = Query("", alias="skip"),
    offset: int = Query(0, ge=0),
    queries: AsyncPersonDuplicatesQueries = Depends(person_duplicates_queries),
) -> Any:
    """Renvoie la paire personne-candidate au dédoublonnage à l'offset donné.

    `skip` : liste CSV de paires `idA-idB` à ignorer pour cette
    session (défilement côté front sans revoir les mêmes candidats).
    Renvoie `{"pair": null}` si aucune paire restante.
    """
    skip_pairs = parse_skip_pairs(skip) if skip else None
    pair = await queries.next_person_duplicate(skip_pairs=skip_pairs, offset=offset)
    return {"pair": pair}


@router.post("/api/admin/person-duplicates/mark-distinct", response_model=OkResponse)
async def mark_persons_distinct(
    body: MarkPersonsDistinct,
    conn: AsyncConnection = Depends(db_conn),
    repo: AsyncPersonRepository = Depends(person_repo),
) -> Any:
    """Marque deux personnes comme distinctes (non-doublon)."""
    if body.person_id_a == body.person_id_b:
        raise HTTPException(
            status_code=400, detail="person_id_a et person_id_b doivent être différents"
        )
    await _mark_persons_distinct(conn, body.person_id_a, body.person_id_b, repo=repo)
    return {"ok": True}


@router.get("/api/admin/person-duplicates/conflicts/count", response_model=TotalCountResponse)
async def count_person_conflict_pairs(
    queries: AsyncPersonDuplicatesQueries = Depends(person_duplicates_queries),
) -> Any:
    """Nombre de paires de personnes co-auteurs d'une même publication.

    Un conflit = deux `person_id` distincts rattachés à la même
    `publication_id` alors que leur forme de nom est compatible →
    suggère un doublon que la déduplication classique n'a pas vu.
    """
    return {"total": await queries.count_person_conflict_pairs()}


@router.get(
    "/api/admin/person-duplicates/conflicts/next", response_model=PersonConflictPairResponse
)
async def next_person_conflict(
    skip: str = Query("", alias="skip"),
    offset: int = Query(0, ge=0),
    queries: AsyncPersonDuplicatesQueries = Depends(person_duplicates_queries),
) -> Any:
    """Renvoie la paire personnes-en-conflit à l'offset donné.

    Même protocole que `/person-duplicates/next` (paire + skip +
    offset) mais pour les conflits co-auteurs plutôt que les
    candidats de similarité de nom.
    """
    skip_pairs = parse_skip_pairs(skip) if skip else set()
    pair = await queries.next_person_conflict(skip_pairs=skip_pairs, offset=offset)
    return {"pair": pair}
