"""Authorships admin router : exclusion source / consolidée, gestion des orphelines.

- Excludes : `POST /api/source-authorships/{src}/{id}/exclude` (niveau source) et `PATCH /api/authorships/{id}/exclude` (niveau consolidé).
- Orphelines : `/api/admin/orphan-authorships/*` — listage et assignation des authorships UCA sans `person_id`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.authorships.assign_orphans import (
    assign_orphan_authorship as _assign_orphan,
)
from application.authorships.assign_orphans import (
    batch_assign_orphan_authorships as _batch_assign_orphan,
)
from application.authorships.core import (
    exclude_authorship,
)
from application.authorships.core import (
    set_source_authorship_excluded as _set_source_authorship_excluded,
)
from application.persons import create_person as _create_person
from application.ports.api.persons_queries import (
    OrphanAuthorshipsResponse,
    OrphanCountResponse,
    PersonsQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from domain.sources import ALL_SOURCES_SET
from interfaces.api.deps import (
    audit_repo_sync,
    authorship_repo_sync,
    person_repo_sync,
    persons_queries_sync,
)
from interfaces.api.models import (
    AssignOrphanAuthorship,
    AuthorshipExcludeResponse,
    BatchAssignOrphanAuthorships,
    ExcludeSourceAuthorship,
    ExcludeSourceAuthorshipResponse,
    OrphanAssignResponse,
    OrphanBatchAssignResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Exclusion d'authorships ──────────────────────────────────────


@router.post(
    "/api/source-authorships/{source}/{authorship_id}/exclude",
    response_model=ExcludeSourceAuthorshipResponse,
)
def exclude_source_authorship(
    source: str,
    authorship_id: int,
    body: ExcludeSourceAuthorship = ExcludeSourceAuthorship(),
    repo: AuthorshipRepository = Depends(authorship_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> ExcludeSourceAuthorshipResponse:
    """Marque/démarque une authorship source comme fausse.

    Si aucune source non exclue n'atteste plus l'authorship consolidée, celle-ci est supprimée.
    """
    _set_source_authorship_excluded(
        authorship_id, source, body.excluded, repo=repo, audit_repo=audit
    )
    return ExcludeSourceAuthorshipResponse(ok=True, excluded=body.excluded)


@router.patch("/api/authorships/{authorship_id}/exclude", response_model=AuthorshipExcludeResponse)
def toggle_authorship_excluded(
    authorship_id: int,
    repo: AuthorshipRepository = Depends(authorship_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> AuthorshipExcludeResponse:
    """Marque un authorship consolidée comme exclu."""
    row = exclude_authorship(authorship_id, repo=repo, audit_repo=audit)
    row_id = row["id"]
    row_excluded = row["excluded"]
    assert isinstance(row_id, int) and isinstance(row_excluded, bool)
    return AuthorshipExcludeResponse(id=row_id, excluded=row_excluded)


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
    queries: PersonsQueries = Depends(persons_queries_sync),
    repo: PersonRepository = Depends(person_repo_sync),
) -> OrphanAssignResponse:
    """Attribue une authorship orpheline à une personne."""
    if body.source not in ALL_SOURCES_SET:
        raise HTTPException(status_code=400, detail=f"Source inconnue: {body.source}")

    person_id = body.person_id
    if body.create_person:
        ln = body.create_person.last_name.strip()
        fn = body.create_person.first_name.strip()
        if not ln:
            raise HTTPException(status_code=400, detail="Nom requis")
        person_id = _create_person(ln, fn, repo=repo)
    elif not person_id:
        raise HTTPException(status_code=400, detail="person_id ou create_person requis")
    if not queries.person_exists(person_id):
        raise HTTPException(status_code=404, detail="Personne introuvable")
    _assign_orphan(person_id, body.source, body.authorship_id, repo=repo)
    return OrphanAssignResponse(person_id=person_id)


@router.post("/api/admin/orphan-authorships/batch-assign", response_model=OrphanBatchAssignResponse)
def batch_assign_orphan_authorships(
    body: BatchAssignOrphanAuthorships,
    queries: PersonsQueries = Depends(persons_queries_sync),
    repo: PersonRepository = Depends(person_repo_sync),
) -> OrphanBatchAssignResponse:
    """Attribue plusieurs authorships orphelines à une même personne."""
    person_id = body.person_id
    sa_ids = [a.authorship_id for a in body.authorships if a.source in ALL_SOURCES_SET]
    if not sa_ids:
        return OrphanBatchAssignResponse(assigned=0)

    if not queries.person_exists(person_id):
        raise HTTPException(status_code=404, detail="Personne introuvable")
    assigned = _batch_assign_orphan(person_id, sa_ids, repo=repo)
    return OrphanBatchAssignResponse(assigned=assigned)
