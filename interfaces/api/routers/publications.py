"""Router /api/publications/* — délègue au port `PublicationsQueries`.

Seul le endpoint POST /api/source-authorships/.../exclude contient encore
du comportement applicatif (invocation d'un use case), pas une query pure.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Connection

from application.authorships import (
    set_source_authorship_excluded_sync as _set_source_authorship_excluded,
)
from application.ports.publications_queries import (
    FacetFilters,
    ListFilters,
    PublicationsQueries,
)
from domain.ports.audit_repository import AuditRepository
from domain.ports.authorship_repository import AuthorshipRepository
from interfaces.api.deps import (
    audit_repo_sync,
    authorship_repo_sync,
    db_conn_sync,
    get_root_structure_id_sync,
    publications_queries_sync,
)
from interfaces.api.filters import parse_int_csv, parse_str_csv
from interfaces.api.models import (
    ExcludeSourceAuthorship,
    ExcludeSourceAuthorshipResponse,
    PublicationDetailResponse,
    PublicationListResponse,
    PublicationsFacetsResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_lab_id(lab_id: str) -> tuple[list[int], bool]:
    """Parse lab_id CSV : retourne (lab_ids, lab_none)."""
    parts = parse_str_csv(lab_id)
    lab_none = "none" in parts
    lab_ids = [int(v) for v in parts if v != "none"]
    return lab_ids, lab_none


@router.get("/api/publications/facets", response_model=PublicationsFacetsResponse)
def publications_facets(
    year: str = Query(""),
    lab_id: str = Query(""),
    doc_type: str = Query(""),
    excluded_doc_type: str = Query(""),
    access: str = Query(""),
    oa_status: str = Query(""),
    source_filter: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    person_id: int | None = Query(None),
    is_corresponding: str = Query(""),
    has_apc: str = Query(""),
    country: str = Query(""),
    hal_status: str = Query(""),
    in_perimeter: str = Query(""),
    subject_id: int | None = Query(None),
    queries: PublicationsQueries = Depends(publications_queries_sync),
) -> Any:
    """Facettes dynamiques pour la page publications."""
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = FacetFilters(
        years=parse_int_csv(year),
        lab_ids=lab_ids,
        lab_none=lab_none,
        doc_types=parse_str_csv(doc_type),
        excluded_types=parse_str_csv(excluded_doc_type),
        access=access,
        oa_status=oa_status,
        source_values=parse_str_csv(source_filter),
        publisher_id=publisher_id,
        journal_id=journal_id,
        person_id=person_id,
        is_corresponding=is_corresponding,
        has_apc=has_apc,
        country_values=parse_str_csv(country),
        hal_status_values=parse_str_csv(hal_status),
        in_perimeter=in_perimeter,
        subject_id=subject_id,
    )
    return queries.publications_facets(
        filters=filters, root_structure_id=get_root_structure_id_sync()
    )


@router.get("/api/publications/years", response_model=list[int])
def all_years(
    queries: PublicationsQueries = Depends(publications_queries_sync),
) -> Any:
    """Liste de toutes les années présentes en base (validées ou non).

    Contrairement à `/stats/years` qui restreint aux années validées,
    cet endpoint remonte l'intégralité des `pub_year` distincts pour
    alimenter le filtre « année » côté admin.
    """
    return queries.all_years()


@router.get("/api/publications/export.csv")
def export_publications_csv(
    search: str = Query(""),
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    source_filter: str = Query(""),
    doc_type: str = Query(""),
    sort: str = Query("year_desc"),
    person_id: int | None = Query(None),
    excluded_doc_type: str = Query(""),
    queries: PublicationsQueries = Depends(publications_queries_sync),
) -> Response:
    """Export CSV des publications (mêmes filtres que list_publications)."""
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = ListFilters(
        search=search,
        lab_ids=lab_ids,
        lab_none=lab_none,
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        journal_id=journal_id,
        oa_status=oa_status,
        source_values=parse_str_csv(source_filter),
        doc_types=parse_str_csv(doc_type),
        excluded_types=parse_str_csv(excluded_doc_type),
        person_id=person_id,
    )
    csv_content = queries.export_publications_csv(
        filters=filters, root_structure_id=get_root_structure_id_sync(), sort=sort
    )
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=publications.csv"},
    )


@router.get("/api/publications/export-theses.csv")
def export_theses_csv(
    search: str = Query(""),
    lab_id: str = Query(""),
    year: str = Query(""),
    access: str = Query(""),
    source_filter: str = Query(""),
    doc_type: str = Query(""),
    sort: str = Query("soutenance_desc"),
    queries: PublicationsQueries = Depends(publications_queries_sync),
) -> Response:
    """Export CSV de la page thèses (filtres + tri identiques à la liste)."""
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = ListFilters(
        search=search,
        lab_ids=lab_ids,
        lab_none=lab_none,
        years=parse_int_csv(year),
        access=access,
        source_values=parse_str_csv(source_filter),
        doc_types=parse_str_csv(doc_type) or ["thesis", "ongoing_thesis"],
    )
    csv_content = queries.export_theses_csv(
        filters=filters, root_structure_id=get_root_structure_id_sync(), sort=sort
    )
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=theses.csv"},
    )


@router.get("/api/publications/{pub_id}", response_model=PublicationDetailResponse)
def get_publication(
    pub_id: int,
    queries: PublicationsQueries = Depends(publications_queries_sync),
) -> Any:
    """Détail complet d'une publication."""
    detail = queries.get_publication_detail(pub_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    return detail


@router.post(
    "/api/source-authorships/{source}/{authorship_id}/exclude",
    response_model=ExcludeSourceAuthorshipResponse,
)
def exclude_source_authorship(
    source: str,
    authorship_id: int,
    body: ExcludeSourceAuthorship = ExcludeSourceAuthorship(),
    conn: Connection = Depends(db_conn_sync),
    repo: AuthorshipRepository = Depends(authorship_repo_sync),
    audit: AuditRepository = Depends(audit_repo_sync),
) -> Any:
    """Marque/démarque une authorship source comme fausse.

    Si aucune source non exclue n'atteste plus l'authorship consolidée,
    celle-ci est supprimée.
    """
    _set_source_authorship_excluded(
        conn, authorship_id, source, body.excluded, repo=repo, audit_repo=audit
    )
    return {"ok": True, "excluded": body.excluded}


@router.get("/api/publications", response_model=PublicationListResponse)
def list_publications(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    access: str = Query(""),
    oa_status: str = Query(""),
    source_filter: str = Query(""),
    doc_type: str = Query(""),
    excluded_doc_type: str = Query(""),
    sort: str = Query("year_desc"),
    person_id: int | None = Query(None),
    is_corresponding: str = Query(""),
    has_apc: str = Query(""),
    country: str = Query(""),
    hal_status: str = Query(""),
    in_perimeter: str = Query(""),
    subject_id: int | None = Query(None),
    queries: PublicationsQueries = Depends(publications_queries_sync),
) -> Any:
    """Liste paginée des publications avec sources, labos et journal rattachés.

    Filtres multiples cumulables. `lab_id` et `year` acceptent des
    listes CSV ; `lab_id=none` = publications sans labo rattaché.
    `sort` : `year_desc` / `year_asc` / `title` / `cited_by`.
    `in_perimeter=yes|no|""` sélectionne les publications dont au
    moins un auteur est in_perimeter. `subject_id` filtre les
    publications annotées par ce sujet.
    """
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = ListFilters(
        search=search,
        lab_ids=lab_ids,
        lab_none=lab_none,
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        journal_id=journal_id,
        access=access,
        oa_status=oa_status,
        source_values=parse_str_csv(source_filter),
        doc_types=parse_str_csv(doc_type),
        excluded_types=parse_str_csv(excluded_doc_type),
        person_id=person_id,
        is_corresponding=is_corresponding,
        has_apc=has_apc,
        country_values=parse_str_csv(country),
        hal_status_values=parse_str_csv(hal_status),
        in_perimeter=in_perimeter,
        subject_id=subject_id,
    )
    return queries.list_publications(
        filters=filters,
        root_structure_id=get_root_structure_id_sync(),
        page=page,
        per_page=per_page,
        sort=sort,
    )
