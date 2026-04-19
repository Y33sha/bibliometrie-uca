"""Router /api/publications/* — délègue les queries à infrastructure/db/queries/publications.py.

Seul le endpoint POST /api/source-authorships/.../exclude contient encore
du comportement applicatif (invocation d'un use case), pas une query pure.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from application.authorships import (
    set_source_authorship_excluded as _set_source_authorship_excluded,
)
from infrastructure.db.queries import publications as pub_queries
from infrastructure.db.queries.publications import FacetFilters, ListFilters
from interfaces.api.deps import get_cursor, get_root_structure_id
from interfaces.api.filters import parse_int_csv, parse_str_csv
from interfaces.api.models import ExcludeSourceAuthorship

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_lab_id(lab_id: str) -> tuple[list[int], bool]:
    """Parse lab_id CSV : retourne (lab_ids, lab_none)."""
    parts = parse_str_csv(lab_id)
    lab_none = "none" in parts
    lab_ids = [int(v) for v in parts if v != "none"]
    return lab_ids, lab_none


@router.get("/api/publications/facets")
async def publications_facets(
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
    )
    with get_cursor() as (cur, _conn):
        return pub_queries.publications_facets(
            cur, filters=filters, root_structure_id=get_root_structure_id()
        )


@router.get("/api/publications/years")
async def all_years() -> Any:
    """Toutes les années disponibles."""
    with get_cursor() as (cur, _conn):
        return pub_queries.all_years(cur)


@router.get("/api/publications/export.csv")
async def export_publications_csv(
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
    with get_cursor() as (cur, _conn):
        csv_content = pub_queries.export_publications_csv(
            cur, filters=filters, root_structure_id=get_root_structure_id(), sort=sort
        )
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=publications.csv"},
    )


@router.get("/api/publications/{pub_id}")
async def get_publication(pub_id: int) -> Any:
    """Détail complet d'une publication."""
    with get_cursor() as (cur, _conn):
        detail = pub_queries.get_publication_detail(cur, pub_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Publication not found")
        return detail


@router.post("/api/source-authorships/{source}/{authorship_id}/exclude")
async def exclude_source_authorship(
    source: str, authorship_id: int, body: ExcludeSourceAuthorship = ExcludeSourceAuthorship()
) -> Any:
    """Marque/démarque une authorship source comme fausse.

    Si aucune source non exclue n'atteste plus l'authorship consolidée,
    celle-ci est supprimée.
    """
    with get_cursor() as (cur, _conn):
        _set_source_authorship_excluded(cur, authorship_id, source, body.excluded)
        return {"ok": True, "excluded": body.excluded}


@router.get("/api/publications")
async def list_publications(
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
) -> Any:
    """Liste des publications avec sources, labos, journal."""
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
    )
    with get_cursor() as (cur, _conn):
        return pub_queries.list_publications(
            cur,
            filters=filters,
            root_structure_id=get_root_structure_id(),
            page=page,
            per_page=per_page,
            sort=sort,
        )
