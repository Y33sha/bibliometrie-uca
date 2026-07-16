"""Router /api/authorships/* et /api/admin/orphan-authorships/* — les gestes admin sur les signatures.

L'exclusion rejette une contribution au niveau consolidé. Les orphelines sont les signatures du périmètre qu'aucune personne ne porte (`person_id` nul) : le router les liste et les attribue.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
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
)

router = APIRouter()


# ── Exclusion d'authorships ──────────────────────────────────────


@router.patch("/api/authorships/{authorship_id}/exclude", response_model=OkResponse)
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


@router.get("/api/admin/orphan-authorships/count", response_model=OrphanCountResponse)
def orphan_authorships_count(
    queries: PersonsQueries = Depends(persons_queries),
) -> OrphanCountResponse:
    """Nombre d'authorships UCA sans person_id."""
    return queries.orphan_authorships_count()


@router.get("/api/admin/orphan-authorships", response_model=OrphanAuthorshipsResponse)
def list_orphan_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    queries: PersonsQueries = Depends(persons_queries),
) -> OrphanAuthorshipsResponse:
    """Liste les authorships UCA sans person_id."""
    return queries.list_orphan_authorships(search=search, page=page, per_page=per_page)


@router.post("/api/admin/orphan-authorships/assign", response_model=OrphanAssignResponse)
def assign_orphan_authorship_endpoint(
    body: AssignOrphanAuthorship,
    conn: Connection = Depends(db_conn),
    queries: PersonsQueries = Depends(persons_queries),
    repo: PersonRepository = Depends(person_repo),
    authorship_repo: AuthorshipRepository = Depends(authorship_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OrphanAssignResponse:
    """Attribue une signature orpheline à une personne.

    Renvoie 409 sur une paire déjà rejetée (`RejectedPairError`), à moins que `force` ne lève le rejet au passage, et sur une signature qui porte déjà une personne (`AuthorshipAlreadyAssignedError`).
    """
    require_known_source(body.source)

    new_person: tuple[str, str] | None = None
    if body.create_person:
        ln = body.create_person.last_name.strip()
        fn = body.create_person.first_name.strip()
        if not ln:
            raise HTTPException(status_code=400, detail="Nom requis")
        new_person = (ln, fn)
    elif not body.person_id:
        raise HTTPException(status_code=400, detail="person_id ou create_person requis")
    elif not queries.person_exists(body.person_id):
        raise HTTPException(status_code=404, detail="Personne introuvable")

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


@router.post("/api/admin/orphan-authorships/batch-assign", response_model=OrphanBatchAssignResponse)
def batch_assign_orphan_authorships(
    body: BatchAssignOrphanAuthorships,
    conn: Connection = Depends(db_conn),
    queries: PersonsQueries = Depends(persons_queries),
    repo: PersonRepository = Depends(person_repo),
    authorship_repo: AuthorshipRepository = Depends(authorship_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OrphanBatchAssignResponse:
    """Attribue plusieurs signatures orphelines à une même personne.

    Renvoie 409 (`RejectedPairError`) dès qu'une paire du lot est déjà rejetée, à moins que `force` ne lève les rejets au passage.
    """
    person_id = body.person_id
    if not body.authorship_ids:
        return OrphanBatchAssignResponse(assigned=0)

    if not queries.person_exists(person_id):
        raise HTTPException(status_code=404, detail="Personne introuvable")
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
