"""Persons admin router : identifiants, fusion, rejet, renommage, détachement.

Toutes les mutations sur personnes. Les opérations sur les authorships en tant que telles (exclude, orphan-authorships) sont dans `admin/authorships.py`. Les lectures publiques restent dans `routers/persons.py`.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection, text

from application.persons import commands as person_commands
from application.ports.api.persons_queries import (
    AmbiguousNameFormsResponse,
    DetachableIntrudersResponse,
    IdentifierConflictsResponse,
    NameFormAuthorshipsResponse,
    PersonOut,
    PersonsQueries,
    SharingPersonOut,
)
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
    IdentifierReassignResponse,
    IdentifierStatusResponse,
    MergePersons,
    MergeResponse,
    NameFormStatusResponse,
    OkResponse,
    ReassignIdentifier,
    RejectPerson,
    RemovedResponse,
    TotalCountResponse,
    UpdateIdentifierStatus,
    UpdateNameFormStatus,
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

    person_commands.add_identifier(
        conn, person_id, data.id_type, id_value, source="manual", repo=repo
    )
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
    conn: Connection = Depends(db_conn_sync),
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> RemovedResponse:
    """Supprime un identifiant d'une personne."""
    person_commands.remove_identifier(
        conn, person_id, id_type, id_value, repo=repo, audit_repo=audit
    )
    return RemovedResponse()


@router.patch("/api/person-identifiers/{ident_id}/status", response_model=IdentifierStatusResponse)
def update_identifier_status(
    ident_id: int,
    body: UpdateIdentifierStatus,
    conn: Connection = Depends(db_conn_sync),
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> IdentifierStatusResponse:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected)."""
    row = person_commands.update_identifier_status(
        conn, ident_id, body.status, repo=repo, audit_repo=audit
    )
    return IdentifierStatusResponse(id=row["id"], status=row["status"])


@router.patch(
    "/api/person-identifiers/{ident_id}/reassign", response_model=IdentifierReassignResponse
)
def reassign_identifier(
    ident_id: int,
    body: ReassignIdentifier,
    conn: Connection = Depends(db_conn_sync),
    queries: PersonsQueries = Depends(persons_queries_sync),
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> IdentifierReassignResponse:
    """Réattribue un identifiant rejeté à une autre personne (status → pending)."""
    if not queries.person_exists(body.person_id):
        raise HTTPException(status_code=404, detail="Personne cible introuvable")
    person_commands.reassign_identifier(conn, ident_id, body.person_id, repo=repo, audit_repo=audit)
    return IdentifierReassignResponse(id=ident_id, person_id=body.person_id, status="pending")


# ── Rejet / renommage / fusion ───────────────────────────────────


@router.patch("/api/persons/{person_id}/reject", response_model=OkResponse)
def reject_person(
    person_id: int,
    body: RejectPerson,
    conn: Connection = Depends(db_conn_sync),
    repo: PersonRepository = Depends(person_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> OkResponse:
    """Marque/démarque une personne comme rejetée."""
    person_commands.set_rejected(conn, person_id, body.rejected, repo=repo, audit_repo=audit)
    return OkResponse()


@router.patch("/api/persons/{person_id}/name", response_model=OkResponse)
def update_person_name(
    person_id: int,
    body: UpdatePersonName,
    conn: Connection = Depends(db_conn_sync),
    repo: PersonRepository = Depends(person_repo_sync),
) -> OkResponse:
    """Modifie le nom/prénom d'une personne."""
    last_name = body.last_name.strip()
    first_name = body.first_name.strip()
    if not last_name:
        raise HTTPException(status_code=400, detail="Le nom est requis")
    person_commands.update_name(conn, person_id, last_name, first_name, repo=repo)
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

    person_commands.merge_person(conn, person_id, source_id, repo=repo, audit_repo=audit)
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
    return queries.name_form_authorships(person_id, name_form)


# ── File de triage : formes de nom ambiguës ──────────────────────


@router.get("/api/admin/ambiguous-name-forms/count", response_model=TotalCountResponse)
def ambiguous_name_forms_count(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> TotalCountResponse:
    """Compteur de l'onglet « Formes ambiguës » (badge)."""
    return TotalCountResponse(total=queries.ambiguous_name_forms_count())


@router.get("/api/admin/ambiguous-name-forms", response_model=AmbiguousNameFormsResponse)
def ambiguous_name_forms(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> AmbiguousNameFormsResponse:
    """Formes de nom portées par ≥2 personnes avec ≥1 lien pending, paginées."""
    return queries.ambiguous_name_forms(page=page, per_page=per_page)


@router.get("/api/admin/identifier-conflicts/count", response_model=TotalCountResponse)
def identifier_conflicts_count(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> TotalCountResponse:
    """Compteur de l'onglet « Conflits d'identifiant » (badge)."""
    return TotalCountResponse(total=queries.identifier_conflicts_count())


@router.get("/api/admin/identifier-conflicts", response_model=IdentifierConflictsResponse)
def identifier_conflicts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> IdentifierConflictsResponse:
    """Paires de personnes au même identifiant brut (ORCID / IdRef / hal_person_id / idHAL),
    paginées : doublons probables ou erreurs d'attribution, à trancher à l'œil."""
    return queries.identifier_conflicts(page=page, per_page=per_page)


# ── File de triage : intrus détachables ──────────────────────────


@router.get("/api/admin/detachable-intruders/count", response_model=TotalCountResponse)
def detachable_intruders_count(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> TotalCountResponse:
    """Compteur de l'onglet « Intrus détachables » (badge)."""
    return TotalCountResponse(total=queries.detachable_intruders_count())


@router.get("/api/admin/detachable-intruders", response_model=DetachableIntrudersResponse)
def detachable_intruders(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> DetachableIntrudersResponse:
    """Personnes rattachées à ≥2 signatures d'une même publication, avec ancre et intrus, paginées :
    l'intrus se détache en rejetant sa forme de nom (`PATCH /api/persons/{id}/name-forms/status`)."""
    return queries.detachable_intruders(page=page, per_page=per_page)


@router.get("/api/admin/persons/{person_id}", response_model=PersonOut)
def person_admin(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonOut:
    """Une personne (projection liste admin) par id — alimente le drawer ouvert hors liste."""
    person = queries.person_admin(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Personne introuvable")
    return person


@router.get(
    "/api/admin/persons/{person_id}/sharing-name-forms", response_model=list[SharingPersonOut]
)
def persons_sharing_name_form(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> list[SharingPersonOut]:
    """Personnes partageant ≥1 forme de nom avec celle-ci (candidates à l'absorption)."""
    return queries.persons_sharing_name_form(person_id)


@router.post(
    "/api/persons/{person_id}/detach-authorships", response_model=DetachAuthorshipsResponse
)
def detach_authorships(
    person_id: int,
    body: DetachAuthorships,
    conn: Connection = Depends(db_conn_sync),
    person_repo_: PersonRepository = Depends(person_repo_sync),
    auth_repo: AuthorshipRepository = Depends(authorship_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> DetachAuthorshipsResponse:
    """Rejette durablement les paires (publication, personne) des authorships
    sources sélectionnées et nettoie les formes de noms."""
    return DetachAuthorshipsResponse.model_validate(
        person_commands.detach_authorships(
            conn,
            person_id,
            [{"source": a.source, "authorship_id": a.authorship_id} for a in body.authorships],
            repo=person_repo_,
            authorship_repo=auth_repo,
            audit_repo=audit,
        )
    )


@router.patch("/api/persons/{person_id}/name-forms/status", response_model=NameFormStatusResponse)
def update_name_form_status(
    person_id: int,
    body: UpdateNameFormStatus,
    conn: Connection = Depends(db_conn_sync),
    repo: PersonRepository = Depends(person_repo_sync),
    auth_repo: AuthorshipRepository = Depends(authorship_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> NameFormStatusResponse:
    """Met à jour le statut d'une forme de nom (pending/confirmed/rejected).

    `rejected` pose le verrou de non-retour ET détache les signatures portant la forme
    (null des source_authorships + suppression des authorships canoniques orphelines) ;
    `confirmed` valide le lien et corrobore les matchs par identifiant sans test de nom."""
    row = person_commands.update_name_form_status(
        conn,
        person_id,
        body.name_form,
        body.status,
        repo=repo,
        authorship_repo=auth_repo,
        audit_repo=audit,
    )
    return NameFormStatusResponse(**row)
