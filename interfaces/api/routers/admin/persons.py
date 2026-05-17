"""Persons admin router : identifiants, fusion, rejet, renommage, détachement.

Toutes les mutations sur personnes. Les opérations sur les authorships en tant que telles (exclude, orphan-authorships) sont dans `admin/authorships.py`. Les lectures publiques restent dans `routers/persons.py`.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection, text

from application.persons import (
    add_identifier as _add_identifier,
)
from application.persons import (
    detach_authorships as _detach_authorships_service,
)
from application.persons import (
    detach_name_form as _detach_name_form,
)
from application.persons import (
    merge_person as _merge_person,
)
from application.persons import (
    reassign_identifier as _reassign_identifier,
)
from application.persons import (
    remove_identifier as _remove_identifier,
)
from application.persons import (
    set_rejected as _set_rejected,
)
from application.persons import (
    update_identifier_status as _update_identifier_status,
)
from application.persons import (
    update_name as _update_name,
)
from application.ports.api.persons_queries import PersonsQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.authorship_repository import AuthorshipRepository
from application.ports.repositories.person_repository import PersonRepository
from domain.persons.identifiers import PUBLIC_PERSON_IDENTIFIER_TYPES
from interfaces.api.deps import (
    audit_repo_sync,
    authorship_repo_sync,
    db_conn_sync,
    person_repo_sync,
    persons_queries_sync,
)
from interfaces.api.models import (
    AddIdentifier,
    AddIdentifierResponse,
    DetachAuthorships,
    DetachAuthorshipsResponse,
    DetachedResponse,
    DetachNameForm,
    IdentifierReassignResponse,
    IdentifierStatusResponse,
    MergePersons,
    MergeResponse,
    NameFormAuthorshipsResponse,
    OkResponse,
    ReassignIdentifier,
    RejectPerson,
    RemovedResponse,
    UpdateIdentifierStatus,
    UpdatePersonName,
)

router = APIRouter()
logger = logging.getLogger(__name__)

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


# ── Gestion des identifiants ─────────────────────────────────────


@router.post("/api/persons/{person_id}/identifiers", response_model=AddIdentifierResponse)
def add_person_identifier(
    person_id: int,
    data: AddIdentifier,
    conn: Connection = Depends(db_conn_sync),
    queries: PersonsQueries = Depends(persons_queries_sync),
    repo: PersonRepository = Depends(person_repo_sync),
) -> AddIdentifierResponse:
    """Ajoute manuellement un identifiant (ORCID ou idHAL) à une personne."""
    if data.id_type not in PUBLIC_PERSON_IDENTIFIER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"id_type doit être l'un de {PUBLIC_PERSON_IDENTIFIER_TYPES}",
        )

    id_value = data.id_value.strip()
    if data.id_type == "orcid":
        id_value = (
            id_value.replace("https://orcid.org/", "").replace("http://orcid.org/", "").strip()
        )
        if not ORCID_RE.match(id_value):
            raise HTTPException(
                status_code=400,
                detail=f"Format ORCID invalide : '{id_value}'. Attendu : 0000-0000-0000-000X",
            )
    if not id_value:
        raise HTTPException(status_code=400, detail="Valeur vide")

    if not queries.person_exists(person_id):
        raise HTTPException(status_code=404, detail="Personne introuvable")

    existing_row = conn.execute(
        text(
            "SELECT id, person_id, status::text AS status "
            "FROM person_identifiers WHERE id_type = :tp AND id_value = :val"
        ),
        {"tp": data.id_type, "val": id_value},
    ).one_or_none()
    was_reassigned = False
    if existing_row:
        if existing_row.person_id == person_id:
            return AddIdentifierResponse(added=False, reason="already_exists")
        if existing_row.status != "rejected":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cet identifiant est déjà attribué à la personne #{existing_row.person_id}"
                ),
            )
        was_reassigned = True

    _add_identifier(person_id, data.id_type, id_value, source="manual", repo=repo)
    return AddIdentifierResponse(
        added=True,
        id_type=data.id_type,
        id_value=id_value,
        reassigned=True if was_reassigned else None,
    )


@router.delete(
    "/api/persons/{person_id}/identifiers/{id_type}/{id_value:path}",
    response_model=RemovedResponse,
)
def remove_person_identifier(
    person_id: int,
    id_type: str,
    id_value: str,
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> RemovedResponse:
    """Supprime un identifiant d'une personne."""
    _remove_identifier(person_id, id_type, id_value, repo=repo, audit_repo=audit)
    return RemovedResponse()


@router.patch("/api/person-identifiers/{ident_id}/status", response_model=IdentifierStatusResponse)
def update_identifier_status(
    ident_id: int,
    body: UpdateIdentifierStatus,
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> IdentifierStatusResponse:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected)."""
    row = _update_identifier_status(ident_id, body.status, repo=repo, audit_repo=audit)
    return IdentifierStatusResponse(id=row["id"], status=row["status"])


@router.patch(
    "/api/person-identifiers/{ident_id}/reassign", response_model=IdentifierReassignResponse
)
def reassign_identifier(
    ident_id: int,
    body: ReassignIdentifier,
    queries: PersonsQueries = Depends(persons_queries_sync),
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> IdentifierReassignResponse:
    """Réattribue un identifiant rejeté à une autre personne (status → pending)."""
    if not queries.person_exists(body.person_id):
        raise HTTPException(status_code=404, detail="Personne cible introuvable")
    _reassign_identifier(ident_id, body.person_id, repo=repo, audit_repo=audit)
    return IdentifierReassignResponse(id=ident_id, person_id=body.person_id, status="pending")


# ── Rejet / renommage / fusion ───────────────────────────────────


@router.patch("/api/persons/{person_id}/reject", response_model=OkResponse)
def reject_person(
    person_id: int,
    body: RejectPerson,
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> OkResponse:
    """Marque/démarque une personne comme rejetée."""
    _set_rejected(person_id, body.rejected, repo=repo, audit_repo=audit)
    return OkResponse()


@router.patch("/api/persons/{person_id}/name", response_model=OkResponse)
def update_person_name(
    person_id: int,
    body: UpdatePersonName,
    repo: PersonRepository = Depends(person_repo_sync),
) -> OkResponse:
    """Modifie le nom/prénom d'une personne."""
    last_name = body.last_name.strip()
    first_name = body.first_name.strip()
    if not last_name:
        raise HTTPException(status_code=400, detail="Le nom est requis")
    _update_name(person_id, last_name, first_name, repo=repo)
    return OkResponse()


@router.post("/api/persons/{person_id}/merge", response_model=MergeResponse)
def merge_persons(
    person_id: int,
    body: MergePersons,
    conn: Connection = Depends(db_conn_sync),
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> MergeResponse:
    """Fusionne une autre personne (source) dans celle-ci (target)."""
    source_id = body.source_id
    if source_id == person_id:
        raise HTTPException(status_code=400, detail="source_id invalide")

    result = conn.execute(
        text("SELECT id FROM persons WHERE id IN (:p, :s)"),
        {"p": person_id, "s": source_id},
    )
    found = {row.id for row in result}
    if person_id not in found:
        raise HTTPException(status_code=404, detail="Personne cible introuvable")
    if source_id not in found:
        raise HTTPException(status_code=404, detail="Personne source introuvable")

    _merge_person(person_id, source_id, repo=repo, audit_repo=audit)
    return MergeResponse(merged=True, source_id=source_id, target_id=person_id)


# ── Formes de noms / détachement authorships ─────────────────────


@router.get(
    "/api/persons/{person_id}/name-form-authorships",
    response_model=NameFormAuthorshipsResponse,
)
def name_form_authorships(
    person_id: int,
    name_form: str = Query(...),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> NameFormAuthorshipsResponse:
    """Authorships sources + autres personnes partageant une forme de nom."""
    return NameFormAuthorshipsResponse.model_validate(
        queries.name_form_authorships(person_id, name_form)
    )


@router.post(
    "/api/persons/{person_id}/detach-authorships", response_model=DetachAuthorshipsResponse
)
def detach_authorships(
    person_id: int,
    body: DetachAuthorships,
    person_repo_: PersonRepository = Depends(person_repo_sync),
    auth_repo: AuthorshipRepository = Depends(authorship_repo_sync),
) -> DetachAuthorshipsResponse:
    """Détache des authorships sources d'une personne et nettoie les formes de noms."""
    return DetachAuthorshipsResponse.model_validate(
        _detach_authorships_service(
            person_id,
            authorships=[
                {"source": a.source, "authorship_id": a.authorship_id} for a in body.authorships
            ],
            name_form=body.name_form,
            repo=person_repo_,
            authorship_repo=auth_repo,
        )
    )


@router.post("/api/persons/{person_id}/detach-name-form", response_model=DetachedResponse)
def detach_name_form(
    person_id: int,
    body: DetachNameForm,
    queries: PersonsQueries = Depends(persons_queries_sync),
    repo: PersonRepository = Depends(person_repo_sync),
) -> DetachedResponse:
    """Détache une forme de nom d'une personne (quand aucune authorship n'y est liée)."""
    remaining = queries.name_form_remaining_authorships(person_id, body.name_form)
    if remaining > 0:
        raise HTTPException(status_code=400, detail="Cette forme a encore des authorships liées")
    _detach_name_form(person_id, body.name_form, repo=repo)
    return DetachedResponse()
