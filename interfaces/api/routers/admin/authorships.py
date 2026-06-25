"""Authorships admin router : exclusion consolidée, gestion des orphelines.

- Exclude : `PATCH /api/authorships/{id}/exclude` (niveau consolidé).
- Orphelines : `/api/admin/orphan-authorships/*` — listage et assignation des authorships UCA sans `person_id`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from application.authorships import commands as authorship_commands
from application.ports.api.persons_queries import (
    OrphanAuthorshipsResponse,
    OrphanCountResponse,
    PersonsQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from domain.sources.registry import ALL_SOURCES_SET
from interfaces.api.deps import (
    audit_repo_sync,
    authorship_repo_sync,
    db_conn_sync,
    person_repo_sync,
    persons_queries_sync,
)
from interfaces.api.models import (
    AssignOrphanAuthorship,
    AuthorshipExcludeResponse,
    BatchAssignOrphanAuthorships,
    OrphanAssignResponse,
    OrphanBatchAssignResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Exclusion d'authorships ──────────────────────────────────────


@router.patch("/api/authorships/{authorship_id}/exclude", response_model=AuthorshipExcludeResponse)
def exclude_authorship_endpoint(
    authorship_id: int,
    conn: Connection = Depends(db_conn_sync),
    repo: AuthorshipRepository = Depends(authorship_repo_sync),
    person_repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> AuthorshipExcludeResponse:
    """Rejette une contribution (« cette personne n'est pas l'auteur »).

    Enregistre la paire (publication, personne) dans `rejected_authorships`,
    détache les sources et supprime la row consolidée ; le rebuild ne la
    recrée pas. Action à sens unique.
    """
    authorship_commands.exclude_authorship(
        conn, authorship_id, repo=repo, person_repo=person_repo, audit_repo=audit
    )
    return AuthorshipExcludeResponse(ok=True)


# ── Authorships orphelines ───────────────────────────────────────


@router.get("/api/admin/orphan-authorships/count", response_model=OrphanCountResponse)
def orphan_authorships_count(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> OrphanCountResponse:
    """Nombre d'authorships UCA sans person_id."""
    return queries.orphan_authorships_count()


@router.get("/api/admin/orphan-authorships", response_model=OrphanAuthorshipsResponse)
def list_orphan_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> OrphanAuthorshipsResponse:
    """Liste les authorships UCA sans person_id."""
    return queries.list_orphan_authorships(search=search, page=page, per_page=per_page)


@router.post("/api/admin/orphan-authorships/assign", response_model=OrphanAssignResponse)
def assign_orphan_authorship_endpoint(
    body: AssignOrphanAuthorship,
    conn: Connection = Depends(db_conn_sync),
    queries: PersonsQueries = Depends(persons_queries_sync),
    repo: PersonRepository = Depends(person_repo_sync),
    authorship_repo: AuthorshipRepository = Depends(authorship_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> OrphanAssignResponse:
    """Attribue une authorship orpheline à une personne.

    Renvoie 409 (`RejectedPairError`) si la paire a déjà été rejetée et que
    `force` est faux ; avec `force`, le rejet est d'abord levé.
    """
    if body.source not in ALL_SOURCES_SET:
        raise HTTPException(status_code=400, detail=f"Source inconnue: {body.source}")

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
    conn: Connection = Depends(db_conn_sync),
    queries: PersonsQueries = Depends(persons_queries_sync),
    repo: PersonRepository = Depends(person_repo_sync),
    authorship_repo: AuthorshipRepository = Depends(authorship_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> OrphanBatchAssignResponse:
    """Attribue plusieurs authorships orphelines à une même personne.

    Renvoie 409 (`RejectedPairError`) si au moins une paire a déjà été rejetée
    et que `force` est faux ; avec `force`, les rejets sont d'abord levés.
    """
    person_id = body.person_id
    sa_ids = [a.authorship_id for a in body.authorships if a.source in ALL_SOURCES_SET]
    if not sa_ids:
        return OrphanBatchAssignResponse(assigned=0)

    if not queries.person_exists(person_id):
        raise HTTPException(status_code=404, detail="Personne introuvable")
    assigned = authorship_commands.batch_assign_orphan_authorships(
        conn,
        person_id,
        sa_ids,
        repo=repo,
        authorship_repo=authorship_repo,
        audit_repo=audit,
        force=body.force,
    )
    return OrphanBatchAssignResponse(assigned=assigned)
