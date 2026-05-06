"""Persons router (async) : directory, search, list, profile, merge, identifiers, admin.

Toutes les queries SQL sont dans :
- `infrastructure/db/queries/persons/` (lectures principales + admin)
- `infrastructure/db/queries/person_duplicates.py` (doublons personnes)

Les mutations délèguent à `application.persons` et `application.authorships`.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.authorships import exclude_authorship as _exclude_authorship
from application.persons import (
    assign_orphan_authorship as _assign_orphan,
)
from application.persons import (
    async_add_identifier as _add_identifier,
)
from application.persons import (
    async_create_person as _create_person,
)
from application.persons import (
    async_merge_person as _merge_person,
)
from application.persons import (
    batch_assign_orphan_authorships as _batch_assign_orphan,
)
from application.persons import (
    detach_authorships as _detach_authorships_service,
)
from application.persons import (
    detach_name_form as _detach_name_form,
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
from domain.sources import ALL_SOURCES_SET
from infrastructure.db.queries import persons as persons_queries
from infrastructure.db.queries.persons import admin as admin_queries
from infrastructure.repositories import async_authorship_repository, async_person_repository
from interfaces.api.async_deps import get_async_cursor, get_sa_connection
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


# ── Endpoints GET principaux (queries dans persons_queries) ──────


@router.get("/api/persons/directory", response_model=PersonDirectoryResponse)
async def persons_directory(
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
) -> Any:
    """Annuaire public des personnes UCA avec ORCID et idHAL."""
    filters = persons_queries.DirectoryFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
    )
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.persons_directory(
            cur, filters=filters, page=page, per_page=per_page, sort=sort
        )


@router.get("/api/persons/search", response_model=list[PersonSearchResult])
async def search_persons(
    q: str = Query("", min_length=2), limit: int = Query(10, ge=1, le=30)
) -> Any:
    """Recherche rapide de personnes (autocomplete)."""
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.search_persons(cur, q=q, limit=limit)


@router.get("/api/persons", response_model=PersonListResponse)
async def list_persons(
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
) -> Any:
    """Liste des personnes avec filtres (admin)."""
    filters = persons_queries.ListFilters(
        search=search,
        department=department,
        role=role,
        linked=linked,
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_rh=has_rh,
    )
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.list_persons(
            cur, filters=filters, page=page, per_page=per_page, sort=sort
        )


@router.get("/api/persons/facets", response_model=PersonsFacetsResponse)
async def persons_facets(
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_idref: str = Query(""),
    has_rh: str = Query(""),
    linked: str = Query(""),
) -> Any:
    """Facettes dynamiques pour la page personnes."""
    filters = persons_queries.FacetFilters(
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
        linked=linked,
    )
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.persons_facets(cur, filters=filters)


@router.get("/api/persons/departments", response_model=list[DepartmentCount])
async def list_departments() -> Any:
    """Liste des départements distincts."""
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.list_departments(cur)


@router.get("/api/persons/roles", response_model=list[RoleCount])
async def list_roles() -> Any:
    """Liste des rôles distincts."""
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.list_roles(cur)


@router.get("/api/persons/stats", response_model=PersonsStatsResponse)
async def persons_stats() -> Any:
    """Statistiques sur les personnes et l'alignement."""
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.persons_stats(cur)


@router.get("/api/persons/{person_id}", response_model=PersonDetail)
async def get_person(person_id: int) -> Any:
    """Détail d'une personne avec auteurs liés."""
    async with get_async_cursor() as (cur, _conn):
        person = await persons_queries.get_person(cur, person_id)
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        return person


@router.get("/api/persons/{person_id}/profile", response_model=PersonProfileResponse)
async def person_profile(person_id: int) -> Any:
    """Profil public complet d'une personne."""
    async with get_async_cursor() as (cur, _conn):
        profile = await persons_queries.person_profile(cur, person_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Person not found")
        return profile


@router.get("/api/persons/{person_id}/theses", response_model=PersonThesesResponse)
async def person_theses(person_id: int) -> Any:
    """Thèses liées à cette personne avec un rôle non-auteur."""
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.person_theses(cur, person_id)


@router.get("/api/persons/{person_id}/addresses", response_model=PersonAddressesResponse)
async def person_addresses(
    person_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> Any:
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.person_addresses(cur, person_id, page=page, per_page=per_page)


@router.get("/api/persons/{person_id}/dashboard", response_model=PersonDashboardResponse)
async def person_dashboard(person_id: int) -> Any:
    """Dashboard personne : publis/an + Open Access."""
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.person_dashboard(cur, person_id)


@router.get("/api/persons/{person_id}/subjects", response_model=list[SubjectFrequency])
async def person_subjects(person_id: int, limit: int = Query(30, ge=1, le=100)) -> Any:
    """Top sujets des publications de cette personne (nuage de mots)."""
    async with get_async_cursor() as (cur, _conn):
        return await persons_queries.person_subjects(cur, person_id, limit=limit)


# ── Gestion des identifiants ─────────────────────────────────────

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


@router.post("/api/persons/{person_id}/identifiers", response_model=AddIdentifierResponse)
async def add_person_identifier(person_id: int, data: AddIdentifier) -> Any:
    """Ajoute manuellement un identifiant (ORCID ou idHAL) à une personne."""
    if data.id_type not in ("orcid", "idhal", "idref"):
        raise HTTPException(status_code=400, detail="id_type doit être 'orcid', 'idhal' ou 'idref'")

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

    async with get_async_cursor() as (cur, _conn):
        if not await admin_queries.person_exists(cur, person_id):
            raise HTTPException(status_code=404, detail="Personne introuvable")

        await cur.execute(
            "SELECT id, person_id, status::text FROM person_identifiers WHERE id_type = %s AND id_value = %s",
            (data.id_type, id_value),
        )
        existing = await cur.fetchone()
        was_reassigned = False
        if existing:
            if existing["person_id"] == person_id:
                return {"added": False, "reason": "already_exists"}
            if existing["status"] != "rejected":
                raise HTTPException(
                    status_code=409,
                    detail=f"Cet identifiant est déjà attribué à la personne #{existing['person_id']}",
                )
            was_reassigned = True

        await _add_identifier(
            cur,
            person_id,
            data.id_type,
            id_value,
            source="manual",
            repo=async_person_repository(cur),
        )
        result = {"added": True, "id_type": data.id_type, "id_value": id_value}
        if was_reassigned:
            result["reassigned"] = True
        return result


@router.delete(
    "/api/persons/{person_id}/identifiers/{id_type}/{id_value:path}",
    response_model=RemovedResponse,
)
async def remove_person_identifier(person_id: int, id_type: str, id_value: str) -> Any:
    """Supprime un identifiant d'une personne."""
    async with get_async_cursor() as (cur, _conn):
        await _remove_identifier(
            cur, person_id, id_type, id_value, repo=async_person_repository(cur)
        )
        return {"removed": True}


@router.patch("/api/person-identifiers/{ident_id}/status", response_model=IdentifierStatusResponse)
async def update_identifier_status(ident_id: int, body: UpdateIdentifierStatus) -> Any:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected)."""
    async with get_async_cursor() as (cur, _conn):
        row = await _update_identifier_status(
            cur, ident_id, body.status, repo=async_person_repository(cur)
        )
        return {"id": row["id"], "status": row["status"]}


@router.patch(
    "/api/person-identifiers/{ident_id}/reassign", response_model=IdentifierReassignResponse
)
async def reassign_identifier(ident_id: int, body: ReassignIdentifier) -> Any:
    """Réattribue un identifiant rejeté à une autre personne (status → pending)."""
    async with get_async_cursor() as (cur, _conn):
        if not await admin_queries.person_exists(cur, body.person_id):
            raise HTTPException(status_code=404, detail="Personne cible introuvable")
        await _reassign_identifier(cur, ident_id, body.person_id, repo=async_person_repository(cur))
        return {"id": ident_id, "person_id": body.person_id, "status": "pending"}


@router.patch("/api/authorships/{authorship_id}/exclude", response_model=AuthorshipExcludeResponse)
async def toggle_authorship_excluded(authorship_id: int) -> Any:
    """Marque un authorship comme exclu."""
    async with get_sa_connection() as conn:
        row = await _exclude_authorship(conn, authorship_id, repo=async_authorship_repository(conn))
        return {"id": row["id"], "excluded": row["excluded"]}


@router.patch("/api/persons/{person_id}/reject", response_model=OkResponse)
async def reject_person(person_id: int, body: RejectPerson) -> Any:
    """Marque/démarque une personne comme rejetée."""
    async with get_async_cursor() as (cur, _conn):
        await _set_rejected(cur, person_id, body.rejected, repo=async_person_repository(cur))
        return {"ok": True}


@router.patch("/api/persons/{person_id}/name", response_model=OkResponse)
async def update_person_name(person_id: int, body: UpdatePersonName) -> Any:
    """Modifie le nom/prénom d'une personne."""
    last_name = body.last_name.strip()
    first_name = body.first_name.strip()
    if not last_name:
        raise HTTPException(status_code=400, detail="Le nom est requis")
    async with get_async_cursor() as (cur, _conn):
        await _update_name(cur, person_id, last_name, first_name, repo=async_person_repository(cur))
        return {"ok": True}


@router.post("/api/persons/{person_id}/merge", response_model=MergeResponse)
async def merge_persons(person_id: int, body: MergePersons) -> Any:
    """Fusionne une autre personne (source) dans celle-ci (target)."""
    source_id = body.source_id
    if source_id == person_id:
        raise HTTPException(status_code=400, detail="source_id invalide")

    async with get_async_cursor() as (cur, _conn):
        await cur.execute("SELECT id FROM persons WHERE id IN (%s, %s)", (person_id, source_id))
        found = {row["id"] for row in await cur.fetchall()}
        if person_id not in found:
            raise HTTPException(status_code=404, detail="Personne cible introuvable")
        if source_id not in found:
            raise HTTPException(status_code=404, detail="Personne source introuvable")

        await _merge_person(cur, person_id, source_id, repo=async_person_repository(cur))
        return {"merged": True, "source_id": source_id, "target_id": person_id}


# ── Authorships orphelines ───────────────────────────────────────


@router.get("/api/admin/orphan-authorships/count", response_model=OrphanCountResponse)
async def orphan_authorships_count() -> Any:
    """Nombre d'authorships UCA sans person_id."""
    async with get_async_cursor() as (cur, _conn):
        return await admin_queries.orphan_authorships_count(cur)


@router.get("/api/admin/orphan-authorships", response_model=OrphanAuthorshipsResponse)
async def list_orphan_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
) -> Any:
    """Liste les authorships UCA sans person_id."""
    async with get_async_cursor() as (cur, _conn):
        return await admin_queries.list_orphan_authorships(
            cur, search=search, page=page, per_page=per_page
        )


@router.post("/api/admin/orphan-authorships/assign", response_model=OrphanAssignResponse)
async def assign_orphan_authorship_endpoint(body: AssignOrphanAuthorship) -> Any:
    """Attribue une authorship orpheline à une personne."""
    if body.source not in ALL_SOURCES_SET:
        raise HTTPException(status_code=400, detail=f"Source inconnue: {body.source}")

    person_id = body.person_id
    async with get_async_cursor() as (cur, _conn):
        if body.create_person:
            ln = body.create_person.last_name.strip()
            fn = body.create_person.first_name.strip()
            if not ln:
                raise HTTPException(status_code=400, detail="Nom requis")
            person_id = await _create_person(cur, ln, fn, repo=async_person_repository(cur))
        elif not person_id:
            raise HTTPException(status_code=400, detail="person_id ou create_person requis")

        if not await admin_queries.person_exists(cur, person_id):
            raise HTTPException(status_code=404, detail="Personne introuvable")

        await _assign_orphan(
            cur, person_id, body.source, body.authorship_id, repo=async_person_repository(cur)
        )
        return {"ok": True, "person_id": person_id}


@router.post("/api/admin/orphan-authorships/batch-assign", response_model=OrphanBatchAssignResponse)
async def batch_assign_orphan_authorships(body: BatchAssignOrphanAuthorships) -> Any:
    """Attribue plusieurs authorships orphelines à une même personne."""
    person_id = body.person_id
    sa_ids = [a.authorship_id for a in body.authorships if a.source in ALL_SOURCES_SET]
    if not sa_ids:
        return {"ok": True, "assigned": 0}

    async with get_async_cursor() as (cur, _conn):
        if not await admin_queries.person_exists(cur, person_id):
            raise HTTPException(status_code=404, detail="Personne introuvable")
        assigned = await _batch_assign_orphan(
            cur, person_id, sa_ids, repo=async_person_repository(cur)
        )
        return {"ok": True, "assigned": assigned}


# ── Formes de noms / détachement authorships ─────────────────────


@router.get(
    "/api/persons/{person_id}/name-form-authorships",
    response_model=NameFormAuthorshipsResponse,
)
async def name_form_authorships(person_id: int, name_form: str = Query(...)) -> Any:
    """Authorships sources + autres personnes partageant une forme de nom."""
    async with get_async_cursor() as (cur, _conn):
        return await admin_queries.name_form_authorships(cur, person_id, name_form)


@router.post(
    "/api/persons/{person_id}/detach-authorships", response_model=DetachAuthorshipsResponse
)
async def detach_authorships(person_id: int, body: DetachAuthorships) -> Any:
    """Détache des authorships sources d'une personne et nettoie les formes de noms."""
    async with get_async_cursor() as (cur, _conn):
        return await _detach_authorships_service(
            cur,
            person_id,
            authorships=[
                {"source": a.source, "authorship_id": a.authorship_id} for a in body.authorships
            ],
            name_form=body.name_form,
            repo=async_person_repository(cur),
            authorship_repo=async_authorship_repository(cur),
        )


@router.post("/api/persons/{person_id}/detach-name-form", response_model=DetachedResponse)
async def detach_name_form(person_id: int, body: DetachNameForm) -> Any:
    """Détache une forme de nom d'une personne (quand aucune authorship n'y est liée)."""
    async with get_async_cursor() as (cur, _conn):
        remaining = await admin_queries.name_form_remaining_authorships(
            cur, person_id, body.name_form
        )
        if remaining > 0:
            raise HTTPException(
                status_code=400, detail="Cette forme a encore des authorships liées"
            )
        await _detach_name_form(cur, person_id, body.name_form, repo=async_person_repository(cur))
        return {"detached": True}


# Les endpoints `/api/hal-problems/*` ont été déplacés dans
# `interfaces/api/routers/hal_problems.py`.
