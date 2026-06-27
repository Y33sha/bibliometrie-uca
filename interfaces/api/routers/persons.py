"""Persons public router : annuaire, recherche, listing, facettes, profil, stats.

Lectures via le port `PersonsQueries` (SQL dans `infrastructure/queries/persons/`). Les mutations sont dans `routers/admin/persons.py`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.api.persons_queries import (
    DepartmentCount,
    DirectoryFilters,
    FacetFilters,
    ListFilters,
    PersonAddressesResponse,
    PersonDashboardResponse,
    PersonDirectoryResponse,
    PersonListResponse,
    PersonProfileResponse,
    PersonSearchResult,
    PersonsFacetsResponse,
    PersonsQueries,
    PersonsStatsResponse,
    PersonThesesResponse,
    RoleCount,
)
from application.ports.api.subjects_queries import SubjectFrequency
from interfaces.api.deps import persons_queries_sync
from interfaces.api.filters import parse_str_csv

router = APIRouter()
logger = logging.getLogger(__name__)


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
    lab_id: int | None = Query(None),
    sort: str = Query("name"),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonDirectoryResponse:
    """Annuaire public des personnes UCA avec ORCID et idHAL.

    `lab_id` (optionnel) scope l'annuaire aux personnes du laboratoire — sert
    l'onglet personnes de la fiche labo (un seul endpoint par entité).
    """
    filters = DirectoryFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
        lab_id=lab_id,
    )
    return queries.persons_directory(filters=filters, page=page, per_page=per_page, sort=sort)


@router.get("/api/persons/search", response_model=list[PersonSearchResult])
def search_persons(
    q: str = Query("", min_length=2),
    limit: int = Query(10, ge=1, le=30),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> list[PersonSearchResult]:
    """Recherche rapide de personnes (autocomplete)."""
    return queries.search_persons(q=q, limit=limit)


@router.get("/api/persons", response_model=PersonListResponse)
def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_idref: str = Query(""),
    has_rh: str = Query(""),
    has_pending_forms: str = Query(""),
    has_pending_identifiers: str = Query(""),
    sort: str = Query("name"),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonListResponse:
    """Liste des personnes avec filtres (admin)."""
    filters = ListFilters(
        search=search,
        department=department,
        role=role,
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
        has_pending_forms=has_pending_forms,
        has_pending_identifiers=has_pending_identifiers,
    )
    return queries.list_persons(filters=filters, page=page, per_page=per_page, sort=sort)


@router.get("/api/persons/facets", response_model=PersonsFacetsResponse)
def persons_facets(
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_idref: str = Query(""),
    has_rh: str = Query(""),
    has_pending_forms: str = Query(""),
    has_pending_identifiers: str = Query(""),
    lab_id: int | None = Query(None),
    search: str = Query(""),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonsFacetsResponse:
    """Facettes dynamiques pour la page personnes (scopables à un labo via `lab_id`)."""
    filters = FacetFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_idref=has_idref,
        has_rh=has_rh,
        has_pending_forms=has_pending_forms,
        has_pending_identifiers=has_pending_identifiers,
        lab_id=lab_id,
    )
    return queries.persons_facets(filters=filters)


@router.get("/api/persons/departments", response_model=list[DepartmentCount])
def list_departments(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> list[DepartmentCount]:
    """Liste des départements distincts."""
    return queries.list_departments()


@router.get("/api/persons/roles", response_model=list[RoleCount])
def list_roles(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> list[RoleCount]:
    """Liste des rôles distincts."""
    return queries.list_roles()


@router.get("/api/persons/stats", response_model=PersonsStatsResponse)
def persons_stats(
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonsStatsResponse:
    """Statistiques sur les personnes et l'alignement."""
    return queries.persons_stats()


@router.get("/api/persons/{person_id}", response_model=PersonProfileResponse)
def person_profile(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonProfileResponse:
    """Profil public complet d'une personne."""
    profile = queries.person_profile(person_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Person not found")
    return profile


@router.get("/api/persons/{person_id}/theses", response_model=PersonThesesResponse)
def person_theses(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonThesesResponse:
    """Thèses liées à cette personne avec un rôle non-auteur."""
    return queries.person_theses(person_id)


@router.get("/api/persons/{person_id}/addresses", response_model=PersonAddressesResponse)
def person_addresses(
    person_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonAddressesResponse:
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    return queries.person_addresses(person_id, page=page, per_page=per_page)


@router.get("/api/persons/{person_id}/dashboard", response_model=PersonDashboardResponse)
def person_dashboard(
    person_id: int,
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> PersonDashboardResponse:
    """Dashboard personne : publis/an + Open Access."""
    return queries.person_dashboard(person_id)


@router.get("/api/persons/{person_id}/subjects", response_model=list[SubjectFrequency])
def person_subjects(
    person_id: int,
    limit: int = Query(30, ge=1, le=100),
    queries: PersonsQueries = Depends(persons_queries_sync),
) -> list[SubjectFrequency]:
    """Top sujets des publications de cette personne (nuage de mots)."""
    return queries.person_subjects(person_id, limit=limit)
