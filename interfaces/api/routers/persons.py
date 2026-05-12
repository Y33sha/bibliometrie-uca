"""Persons router : directory, search, list, profile, merge, identifiers, admin.

Lectures via le port `PersonsQueries` (toutes les queries SQL sont dans
`infrastructure/db/queries/persons/`). Les mutations délèguent à
`application.persons` et `application.authorships`.
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection, text

from application.authorships.assign_orphans import (
    assign_orphan_authorship as _assign_orphan,
)
from application.authorships.assign_orphans import (
    batch_assign_orphan_authorships as _batch_assign_orphan,
)
from application.authorships.core import exclude_authorship
from application.persons import (
    add_identifier as _add_identifier,
)
from application.persons import (
    create_person as _create_person,
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
from application.ports.persons_queries import (
    DirectoryFilters,
    FacetFilters,
    ListFilters,
    PersonsQueries,
)
from domain.persons.identifiers import PUBLIC_PERSON_IDENTIFIER_TYPES
from domain.ports.audit_repository import AuditRepository
from domain.ports.authorship_repository import AuthorshipRepository
from domain.ports.person_repository import PersonRepository
from domain.sources import ALL_SOURCES_SET
from interfaces.api.deps import (
    audit_repo_sync,
    authorship_repo_sync,
    db_conn_sync,
    person_repo_sync,
    persons_queries_sync,
)
from interfaces.api.filters import parse_str_csv
from interfaces.api.models import (
    AddIdentifier,
    AddIdentifierResponse,
    AssignOrphanAuthorship,
    AuthorshipExcludeResponse,
    BatchAssignOrphanAuthorships,
    DepartmentCount,
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
    OrphanAssignResponse,
    OrphanAuthorshipsResponse,
    OrphanBatchAssignResponse,
    OrphanCountResponse,
    PersonAddressesResponse,
    PersonDashboardResponse,
    PersonDetail,
    PersonDirectoryResponse,
    PersonListResponse,
    PersonProfileResponse,
    PersonSearchResult,
    PersonsFacetsResponse,
    PersonsStatsResponse,
    PersonThesesResponse,
    ReassignIdentifier,
    RejectPerson,
    RemovedResponse,
    RoleCount,
    SubjectFrequency,
    UpdateIdentifierStatus,
    UpdatePersonName,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Endpoints GET principaux ─────────────────────────────────────


@router.get("/api/persons/directory", response_model=PersonDirectoryResponse)
def persons_directory(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_idref: str = Query(""),
    has_rh: str = Query(""),
    sort: str = Query("name"),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonDirectoryResponse:
    """Annuaire public des personnes UCA avec ORCID et idHAL."""
    filters = DirectoryFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
    )
    return PersonDirectoryResponse.model_validate(
        queries.persons_directory(filters=filters, page=page, per_page=per_page, sort=sort)
    )


@router.get("/api/persons/search", response_model=list[PersonSearchResult])
def search_persons(
    q: str = Query("", min_length=2),
    limit: int = Query(10, ge=1, le=30),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> list[PersonSearchResult]:
    """Recherche rapide de personnes (autocomplete)."""
    return [PersonSearchResult.model_validate(r) for r in queries.search_persons(q=q, limit=limit)]


@router.get("/api/persons", response_model=PersonListResponse)
def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    department: str = Query(""),
    role: str = Query(""),
    linked: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_rh: str = Query(""),
    sort: str = Query("name"),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonListResponse:
    """Liste des personnes avec filtres (admin)."""
    filters = ListFilters(
        search=search,
        department=department,
        role=role,
        linked=linked,
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_rh=has_rh,
    )
    return PersonListResponse.model_validate(
        queries.list_persons(filters=filters, page=page, per_page=per_page, sort=sort)
    )


@router.get("/api/persons/facets", response_model=PersonsFacetsResponse)
def persons_facets(
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_idref: str = Query(""),
    has_rh: str = Query(""),
    linked: str = Query(""),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonsFacetsResponse:
    """Facettes dynamiques pour la page personnes."""
    filters = FacetFilters(
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
        linked=linked,
    )
    return PersonsFacetsResponse.model_validate(queries.persons_facets(filters=filters))


@router.get("/api/persons/departments", response_model=list[DepartmentCount])
def list_departments(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> list[DepartmentCount]:
    """Liste des départements distincts."""
    return [DepartmentCount.model_validate(r) for r in queries.list_departments()]


@router.get("/api/persons/roles", response_model=list[RoleCount])
def list_roles(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> list[RoleCount]:
    """Liste des rôles distincts."""
    return [RoleCount.model_validate(r) for r in queries.list_roles()]


@router.get("/api/persons/stats", response_model=PersonsStatsResponse)
def persons_stats(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonsStatsResponse:
    """Statistiques sur les personnes et l'alignement."""
    return PersonsStatsResponse.model_validate(queries.persons_stats())


@router.get("/api/persons/{person_id}", response_model=PersonDetail)
def get_person(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonDetail:
    """Détail d'une personne avec auteurs liés."""
    person = queries.get_person(person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return PersonDetail.model_validate(person)


@router.get("/api/persons/{person_id}/profile", response_model=PersonProfileResponse)
def person_profile(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonProfileResponse:
    """Profil public complet d'une personne."""
    profile = queries.person_profile(person_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Person not found")
    return PersonProfileResponse.model_validate(profile)


@router.get("/api/persons/{person_id}/theses", response_model=PersonThesesResponse)
def person_theses(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonThesesResponse:
    """Thèses liées à cette personne avec un rôle non-auteur."""
    return PersonThesesResponse.model_validate(queries.person_theses(person_id))


@router.get("/api/persons/{person_id}/addresses", response_model=PersonAddressesResponse)
def person_addresses(
    person_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonAddressesResponse:
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    return PersonAddressesResponse.model_validate(
        queries.person_addresses(person_id, page=page, per_page=per_page)
    )


@router.get("/api/persons/{person_id}/dashboard", response_model=PersonDashboardResponse)
def person_dashboard(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonDashboardResponse:
    """Dashboard personne : publis/an + Open Access."""
    return PersonDashboardResponse.model_validate(queries.person_dashboard(person_id))


@router.get("/api/persons/{person_id}/subjects", response_model=list[SubjectFrequency])
def person_subjects(
    person_id: int,
    limit: int = Query(30, ge=1, le=100),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> list[SubjectFrequency]:
    """Top sujets des publications de cette personne (nuage de mots)."""
    return [
        SubjectFrequency.model_validate(r) for r in queries.person_subjects(person_id, limit=limit)
    ]


# ── Gestion des identifiants ─────────────────────────────────────

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


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


@router.patch("/api/authorships/{authorship_id}/exclude", response_model=AuthorshipExcludeResponse)
def toggle_authorship_excluded(
    authorship_id: int,
    repo: AuthorshipRepository = Depends(authorship_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> AuthorshipExcludeResponse:
    """Marque un authorship comme exclu."""
    row = exclude_authorship(authorship_id, repo=repo, audit_repo=audit)
    return AuthorshipExcludeResponse(id=row["id"], excluded=row["excluded"])


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


# ── Authorships orphelines ───────────────────────────────────────


@router.get("/api/admin/orphan-authorships/count", response_model=OrphanCountResponse)
def orphan_authorships_count(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> OrphanCountResponse:
    """Nombre d'authorships UCA sans person_id."""
    return OrphanCountResponse.model_validate(queries.orphan_authorships_count())


@router.get("/api/admin/orphan-authorships", response_model=OrphanAuthorshipsResponse)
def list_orphan_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> OrphanAuthorshipsResponse:
    """Liste les authorships UCA sans person_id."""
    return OrphanAuthorshipsResponse.model_validate(
        queries.list_orphan_authorships(search=search, page=page, per_page=per_page)
    )


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


# Les endpoints `/api/hal-problems/*` ont été déplacés dans
# `interfaces/api/routers/hal_problems.py`.
