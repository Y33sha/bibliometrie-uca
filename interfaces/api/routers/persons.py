"""Persons public router : annuaire, recherche, listing, facettes, profil, stats.

Lectures via le port `PersonsQueries` (SQL dans `infrastructure/queries/persons/`). Les mutations sont dans `routers/admin/persons.py`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.api.persons_queries import (
    DirectoryFilters,
    FacetFilters,
    ListFilters,
    PersonsQueries,
)
from application.ports.api.subjects_queries import SubjectFrequency
from interfaces.api.deps import persons_queries_sync
from interfaces.api.filters import parse_str_csv
from interfaces.api.models import (
    DepartmentCount,
    PersonAddressesResponse,
    PersonDashboardResponse,
    PersonDirectoryResponse,
    PersonListResponse,
    PersonProfileResponse,
    PersonSearchResult,
    PersonsFacetsResponse,
    PersonsStatsResponse,
    PersonThesesResponse,
    RoleCount,
)

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


@router.get("/api/persons/{person_id}", response_model=PersonProfileResponse)
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
