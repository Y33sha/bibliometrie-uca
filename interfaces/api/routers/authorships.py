"""Router des signatures : exclusion d'une contribution, et revue des signatures orphelines. Sert `/api/authorships/*`.

L'exclusion rejette une contribution au niveau consolidé. Les orphelines sont les signatures du périmètre qu'aucune personne ne porte (`person_id` nul) : le router les liste et les attribue, sous `/orphans`.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from application.ports.api.persons_queries import (
    OrphanAuthorshipsResponse,
    OrphanCountResponse,
    PersonsQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from application.services.authorships import commands as authorship_commands
from domain.sources.registry import require_known_source
from interfaces.api.deps import (
    audit_repo,
    authorship_repo,
    db_conn,
    person_repo,
    persons_queries,
)
from interfaces.api.models import (
    AssignOrphanAuthorship,
    BatchAssignOrphanAuthorships,
    OkResponse,
    OrphanAssignResponse,
    OrphanBatchAssignResponse,
    RejectedPairsResponse,
)

router = APIRouter(prefix="/api/authorships", tags=["authorships"])


# ── Exclusion d'authorships ──────────────────────────────────────


@router.patch("/{authorship_id}/exclude", response_model=OkResponse)
def exclude_authorship_endpoint(
    authorship_id: int,
    conn: Connection = Depends(db_conn),
    repo: AuthorshipRepository = Depends(authorship_repo),
    person_repo: PersonRepository = Depends(person_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OkResponse:
    """Rejette une contribution : cette personne n'a pas signé cette publication.

    Enregistre la paire (publication, personne) dans `rejected_authorships`, détache les signatures sources et supprime la ligne consolidée. La table de rejet vaut verrou : les reconstructions ultérieures respectent l'arbitrage. Le geste est à sens unique.
    """
    authorship_commands.exclude_authorship(
        conn, authorship_id, repo=repo, person_repo=person_repo, audit_repo=audit
    )
    return OkResponse()


# ── Authorships orphelines ───────────────────────────────────────


@router.get("/orphans/count", response_model=OrphanCountResponse)
def orphan_authorships_count(
    queries: PersonsQueries = Depends(persons_queries),
) -> OrphanCountResponse:
    """Nombre d'authorships UCA sans person_id."""
    return queries.orphan_authorships_count()


@router.get("/orphans", response_model=OrphanAuthorshipsResponse)
def list_orphan_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    queries: PersonsQueries = Depends(persons_queries),
) -> OrphanAuthorshipsResponse:
    """Liste les authorships UCA sans person_id."""
    return queries.list_orphan_authorships(search=search, page=page, per_page=per_page)


@router.post(
    "/orphans/assign",
    response_model=OrphanAssignResponse,
    responses={409: {"model": RejectedPairsResponse}},
)
def assign_orphan_authorship_endpoint(
    body: AssignOrphanAuthorship,
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
    authorship_repo: AuthorshipRepository = Depends(authorship_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OrphanAssignResponse:
    """Attribue une signature orpheline à une personne.

    Renvoie 400 sans `person_id` ni `create_person`, et sans patronyme à la création (`assign_orphan_authorship`) ; 404 sur une personne ou une signature introuvable ; 409 sur une paire déjà rejetée (`RejectedPairError`), à moins que `force` ne lève le rejet au passage, et sur une signature qui porte déjà une personne (`AuthorshipAlreadyAssignedError`).
    """
    require_known_source(body.source)

    new_person: tuple[str, str] | None = None
    if body.create_person:
        new_person = (body.create_person.last_name, body.create_person.first_name)

    person_id = authorship_commands.assign_orphan_authorship(
        conn,
        body.source,
        body.authorship_id,
        person_id=body.person_id,
        new_person=new_person,
        repo=repo,
        authorship_repo=authorship_repo,
        audit_repo=audit,
        force=body.force,
    )
    return OrphanAssignResponse(person_id=person_id)


@router.post(
    "/orphans/batch-assign",
    response_model=OrphanBatchAssignResponse,
    responses={409: {"model": RejectedPairsResponse}},
)
def batch_assign_orphan_authorships(
    body: BatchAssignOrphanAuthorships,
    conn: Connection = Depends(db_conn),
    repo: PersonRepository = Depends(person_repo),
    authorship_repo: AuthorshipRepository = Depends(authorship_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OrphanBatchAssignResponse:
    """Attribue plusieurs signatures orphelines à une même personne.

    Renvoie 404 sur une personne introuvable, 409 (`RejectedPairError`) dès qu'une paire du lot est déjà rejetée, à moins que `force` ne lève les rejets au passage.
    """
    person_id = body.person_id
    if not body.authorship_ids:
        return OrphanBatchAssignResponse(assigned=0)

    assigned = authorship_commands.batch_assign_orphan_authorships(
        conn,
        person_id,
        body.authorship_ids,
        repo=repo,
        authorship_repo=authorship_repo,
        audit_repo=audit,
        force=body.force,
    )
    return OrphanBatchAssignResponse(assigned=assigned)
