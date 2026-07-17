"""Router /api/publications/* — les publications : listes, facettes, détail, export, servis par le port `PublicationsQueries`."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from application.ports.api.entity_facet import EntityFacetResponse, EntityLabelResponse
from application.ports.api.publications_queries import (
    FacetFilters,
    ListFilters,
    PublicationDetailResponse,
    PublicationListResponse,
    PublicationsFacetsResponse,
    PublicationsQueries,
)
from interfaces.api.deps import (
    publications_queries,
)
from interfaces.api.filters import parse_int_csv, parse_str_csv

router = APIRouter()


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
    search: str = Query(""),
    queries: PublicationsQueries = Depends(publications_queries),
) -> PublicationsFacetsResponse:
    """Facettes dynamiques pour la page publications."""
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = FacetFilters(
        years=parse_int_csv(year),
        lab_ids=lab_ids,
        lab_none=lab_none,
        doc_types=parse_str_csv(doc_type),
        excluded_types=parse_str_csv(excluded_doc_type),
        access=parse_str_csv(access),
        oa_status=parse_str_csv(oa_status),
        source_values=parse_str_csv(source_filter),
        publisher_id=publisher_id,
        journal_id=journal_id,
        person_id=person_id,
        is_corresponding=parse_str_csv(is_corresponding),
        has_apc=parse_str_csv(has_apc),
        country_values=parse_str_csv(country),
        hal_status_values=parse_str_csv(hal_status),
        in_perimeter=parse_str_csv(in_perimeter),
        subject_id=subject_id,
        search=search,
    )
    return queries.publications_facets(filters=filters)


@router.get("/api/publications/facets/entities", response_model=EntityFacetResponse)
def publications_entity_facet(
    kind: Literal["publisher", "journal"] = Query(...),
    entity_search: str = Query(""),
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
    search: str = Query(""),
    queries: PublicationsQueries = Depends(publications_queries),
) -> EntityFacetResponse:
    """Facette contextuelle des éditeurs ou des revues : les premières entités sous les filtres actifs, avec leur décompte.

    Les entités sont corrélées entre elles. `entity_search` cherche dans leurs noms, là où `search` filtre les publications sur leur titre et leurs sujets.
    """
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = FacetFilters(
        years=parse_int_csv(year),
        lab_ids=lab_ids,
        lab_none=lab_none,
        doc_types=parse_str_csv(doc_type),
        excluded_types=parse_str_csv(excluded_doc_type),
        access=parse_str_csv(access),
        oa_status=parse_str_csv(oa_status),
        source_values=parse_str_csv(source_filter),
        publisher_id=publisher_id,
        journal_id=journal_id,
        person_id=person_id,
        is_corresponding=parse_str_csv(is_corresponding),
        has_apc=parse_str_csv(has_apc),
        country_values=parse_str_csv(country),
        hal_status_values=parse_str_csv(hal_status),
        in_perimeter=parse_str_csv(in_perimeter),
        subject_id=subject_id,
        search=search,
    )
    return queries.publications_entity_facet(
        kind=kind,
        search=entity_search,
        filters=filters,
    )


@router.get("/api/publications/facets/entity-label", response_model=EntityLabelResponse)
def publications_entity_label(
    kind: Literal["publisher", "journal"] = Query(...),
    entity_id: int = Query(...),
    queries: PublicationsQueries = Depends(publications_queries),
) -> EntityLabelResponse:
    """Libellé d'une revue ou d'un éditeur par son identifiant.

    Sert à réafficher une pastille de facette restaurée depuis l'URL, qui porte l'identifiant seul : il est l'état canonique de la sélection.
    """
    return queries.resolve_entity_label(kind=kind, entity_id=entity_id)


@router.get("/api/publications/export.csv")
def export_publications_csv(
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
    columns: str = Query(""),
    queries: PublicationsQueries = Depends(publications_queries),
) -> Response:
    """Export CSV des publications, fidèle au tableau affiché : mêmes filtres, et mêmes colonnes que celles listées dans `columns`."""
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = ListFilters(
        search=search,
        lab_ids=lab_ids,
        lab_none=lab_none,
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        journal_id=journal_id,
        access=parse_str_csv(access),
        oa_status=parse_str_csv(oa_status),
        source_values=parse_str_csv(source_filter),
        doc_types=parse_str_csv(doc_type),
        excluded_types=parse_str_csv(excluded_doc_type),
        person_id=person_id,
        is_corresponding=parse_str_csv(is_corresponding),
        has_apc=parse_str_csv(has_apc),
        country_values=parse_str_csv(country),
        hal_status_values=parse_str_csv(hal_status),
        in_perimeter=parse_str_csv(in_perimeter),
        subject_id=subject_id,
    )
    csv_content = queries.export_publications_csv(
        filters=filters,
        sort=sort,
        columns=parse_str_csv(columns),
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
    queries: PublicationsQueries = Depends(publications_queries),
) -> Response:
    """Export CSV de la page thèses (filtres + tri identiques à la liste)."""
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = ListFilters(
        search=search,
        lab_ids=lab_ids,
        lab_none=lab_none,
        years=parse_int_csv(year),
        access=parse_str_csv(access),
        source_values=parse_str_csv(source_filter),
        doc_types=parse_str_csv(doc_type) or ["thesis", "ongoing_thesis"],
    )
    csv_content = queries.export_theses_csv(filters=filters, sort=sort)
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=theses.csv"},
    )


@router.get("/api/publications/{pub_id}", response_model=PublicationDetailResponse)
def get_publication(
    pub_id: int,
    queries: PublicationsQueries = Depends(publications_queries),
) -> PublicationDetailResponse:
    """Détail complet d'une publication."""
    detail = queries.get_publication_detail(pub_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Publication introuvable")
    return detail


@router.get("/api/publications", response_model=PublicationListResponse)
def list_publications(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
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
    queries: PublicationsQueries = Depends(publications_queries),
) -> PublicationListResponse:
    """Liste paginée des publications avec sources, labos et journal rattachés.

    Filtres multiples cumulables. `lab_id` et `year` acceptent des listes CSV ; `lab_id=none` = publications sans labo rattaché. `sort` : `year_desc` / `year_asc` / `title` / `cited_by`. `in_perimeter=yes|no|""` sélectionne les publications dont au moins un auteur est in_perimeter. `subject_id` filtre les publications annotées par ce sujet.
    """
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = ListFilters(
        search=search,
        lab_ids=lab_ids,
        lab_none=lab_none,
        years=parse_int_csv(year),
        publisher_id=publisher_id,
        journal_id=journal_id,
        access=parse_str_csv(access),
        oa_status=parse_str_csv(oa_status),
        source_values=parse_str_csv(source_filter),
        doc_types=parse_str_csv(doc_type),
        excluded_types=parse_str_csv(excluded_doc_type),
        person_id=person_id,
        is_corresponding=parse_str_csv(is_corresponding),
        has_apc=parse_str_csv(has_apc),
        country_values=parse_str_csv(country),
        hal_status_values=parse_str_csv(hal_status),
        in_perimeter=parse_str_csv(in_perimeter),
        subject_id=subject_id,
    )
    return queries.list_publications(
        filters=filters,
        page=page,
        per_page=per_page,
        sort=sort,
    )
