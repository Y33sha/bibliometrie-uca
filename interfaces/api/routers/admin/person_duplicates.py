"""Router /api/admin/person-duplicates/*."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.persons import mark_distinct as _mark_persons_distinct
from application.ports.api.person_duplicates_queries import (
    PersonDuplicatesQueries,
    parse_skip_pairs,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.person_repository import PersonRepository
from interfaces.api.deps import (
    audit_repo_sync,
    person_duplicates_queries_sync,
    person_repo_sync,
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
def count_person_duplicates(
    queries: PersonDuplicatesQueries = Depends(person_duplicates_queries_sync),
) -> TotalCountResponse:
    """Comptage des paires candidates doublons-personnes."""
    return TotalCountResponse(total=queries.count_person_duplicates())


@router.get("/api/admin/person-duplicates/next", response_model=PersonDuplicatePairResponse)
def next_person_duplicate(
    skip: str = Query("", alias="skip"),
    offset: int = Query(0, ge=0),
    queries: PersonDuplicatesQueries = Depends(person_duplicates_queries_sync),
) -> PersonDuplicatePairResponse:
    """Renvoie la paire personne-candidate au dédoublonnage à l'offset donné.

    `skip` : liste CSV de paires `idA-idB` à ignorer pour cette
    session (défilement côté front sans revoir les mêmes candidats).
    Renvoie `{"pair": null}` si aucune paire restante.
    """
    skip_pairs = parse_skip_pairs(skip) if skip else None
    pair = queries.next_person_duplicate(skip_pairs=skip_pairs, offset=offset)
    return PersonDuplicatePairResponse(pair=pair)


@router.post("/api/admin/person-duplicates/mark-distinct", response_model=OkResponse)
def mark_persons_distinct(
    body: MarkPersonsDistinct,
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> OkResponse:
    """Marque deux personnes comme distinctes (non-doublon)."""
    if body.person_id_a == body.person_id_b:
        raise HTTPException(
            status_code=400, detail="person_id_a et person_id_b doivent être différents"
        )
    _mark_persons_distinct(body.person_id_a, body.person_id_b, repo=repo, audit_repo=audit)
    return OkResponse()


@router.get("/api/admin/person-duplicates/conflicts/count", response_model=TotalCountResponse)
def count_person_conflict_pairs(
    queries: PersonDuplicatesQueries = Depends(person_duplicates_queries_sync),
) -> TotalCountResponse:
    """Nombre de paires de personnes co-auteurs d'une même publication.

    Un conflit = deux `person_id` distincts rattachés à la même
    `publication_id` alors que leur forme de nom est compatible →
    suggère un doublon que la déduplication classique n'a pas vu.
    """
    return TotalCountResponse(total=queries.count_person_conflict_pairs())


@router.get(
    "/api/admin/person-duplicates/conflicts/next", response_model=PersonConflictPairResponse
)
def next_person_conflict(
    skip: str = Query("", alias="skip"),
    offset: int = Query(0, ge=0),
    queries: PersonDuplicatesQueries = Depends(person_duplicates_queries_sync),
) -> PersonConflictPairResponse:
    """Renvoie la paire personnes-en-conflit à l'offset donné.

    Même protocole que `/person-duplicates/next` (paire + skip +
    offset) mais pour les conflits co-auteurs plutôt que les
    candidats de similarité de nom.
    """
    skip_pairs = parse_skip_pairs(skip) if skip else set()
    pair = queries.next_person_conflict(skip_pairs=skip_pairs, offset=offset)
    return PersonConflictPairResponse(pair=pair)
