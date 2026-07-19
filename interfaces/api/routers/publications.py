"""Router des publications : listes, facettes, détail, export, et revue des doublons. Sert `/api/publications/*`.

Les lectures passent par les ports `PublicationsQueries` et `PublicationDuplicatesQueries`, les écritures par les command handlers de `application.services.publications.commands`.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Connection

from application.ports.api.entity_facet import EntityFacetResponse, EntityLabelResponse
from application.ports.api.publication_duplicates_queries import (
    PubDuplicateNextResponse,
    PublicationDuplicatesQueries,
)
from application.ports.api.publications_queries import (
    PublicationDetailResponse,
    PublicationFilters,
    PublicationListResponse,
    PublicationsFacetsResponse,
    PublicationSort,
    PublicationsQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.publications import commands as publication_commands
from interfaces.api.deps import (
    audit_repo,
    db_conn,
    publication_duplicates_queries,
    publication_repo,
    publications_queries,
)
from interfaces.api.filters import parse_int_csv, parse_str_csv
from interfaces.api.models import (
    MarkDistinctPublications,
    MergePublications,
    OkResponse,
    PublicationMergeResponse,
)

router = APIRouter(prefix="/api/publications", tags=["publications"])


def _parse_lab_id(lab_id: str) -> tuple[list[int], bool]:
    """Découpe `lab_id` en identifiants de laboratoires et en drapeau « sans laboratoire ».

    La sentinelle `none` se mêle aux identifiants dans la même liste : `lab_id=12,none` retient les publications que le laboratoire 12 signe et celles qu'aucun laboratoire ne signe.
    """
    parts = parse_str_csv(lab_id)
    return [int(v) for v in parts if v != "none"], "none" in parts


@dataclass(frozen=True, slots=True)
class PublicationFilterParams:
    """Filtres de la page publications tels que la query string les porte.

    Injectés par `Depends()` : la liste, les deux facettes et l'export répondent aux mêmes
    questions sur le même ensemble, et les déclarer une fois les tient d'accord.

    Les valeurs multiples se séparent par des virgules. `lab_id` accepte la sentinelle `none`,
    qui retient les publications qu'aucun laboratoire ne signe, et se combine aux identifiants.
    """

    search: Annotated[str, Query()] = ""
    lab_id: Annotated[str, Query()] = ""
    year: Annotated[str, Query()] = ""
    publisher_id: Annotated[int | None, Query()] = None
    journal_id: Annotated[int | None, Query()] = None
    person_id: Annotated[int | None, Query()] = None
    subject_id: Annotated[int | None, Query()] = None
    access: Annotated[str, Query()] = ""
    oa_status: Annotated[str, Query()] = ""
    source_filter: Annotated[str, Query()] = ""
    doc_type: Annotated[str, Query()] = ""
    excluded_doc_type: Annotated[str, Query()] = ""
    is_corresponding: Annotated[str, Query()] = ""
    has_apc: Annotated[str, Query()] = ""
    country: Annotated[str, Query()] = ""
    hal_status: Annotated[str, Query()] = ""
    in_perimeter: Annotated[str, Query()] = ""

    def to_filters(self) -> PublicationFilters:
        """Traduit la query string en filtres du port."""
        lab_ids, lab_none = _parse_lab_id(self.lab_id)
        return PublicationFilters(
            search=self.search,
            lab_ids=lab_ids,
            lab_none=lab_none,
            years=parse_int_csv(self.year),
            publisher_id=self.publisher_id,
            journal_id=self.journal_id,
            person_id=self.person_id,
            subject_id=self.subject_id,
            access=parse_str_csv(self.access),
            oa_status=parse_str_csv(self.oa_status),
            source_values=parse_str_csv(self.source_filter),
            doc_types=parse_str_csv(self.doc_type),
            excluded_types=parse_str_csv(self.excluded_doc_type),
            is_corresponding=parse_str_csv(self.is_corresponding),
            has_apc=parse_str_csv(self.has_apc),
            country_values=parse_str_csv(self.country),
            hal_status_values=parse_str_csv(self.hal_status),
            in_perimeter=parse_str_csv(self.in_perimeter),
        )


Filters = Annotated[PublicationFilterParams, Depends()]


@router.get("/facets", response_model=PublicationsFacetsResponse)
def publications_facets(
    filters: Filters,
    queries: PublicationsQueries = Depends(publications_queries),
) -> PublicationsFacetsResponse:
    """Décomptes par option des facettes de la liste des publications.

    Chaque facette écarte sa propre dimension de la clause WHERE : son décompte annonce le nombre de publications atteignables si l'option était cochée ou décochée.
    """
    return queries.publications_facets(filters=filters.to_filters())


@router.get("/facets/entities", response_model=EntityFacetResponse)
def publications_entity_facet(
    filters: Filters,
    kind: Literal["publisher", "journal"] = Query(...),
    entity_search: str = Query(""),
    queries: PublicationsQueries = Depends(publications_queries),
) -> EntityFacetResponse:
    """Facette contextuelle des éditeurs ou des revues : les premières entités sous les filtres actifs, avec leur décompte.

    Les entités sont corrélées entre elles. `entity_search` cherche dans leurs noms, là où `search` filtre les publications sur leur titre et leurs sujets.
    """
    return queries.publications_entity_facet(
        kind=kind,
        search=entity_search,
        filters=filters.to_filters(),
    )


@router.get("/facets/entity-label", response_model=EntityLabelResponse)
def publications_entity_label(
    kind: Literal["publisher", "journal"] = Query(...),
    entity_id: int = Query(...),
    queries: PublicationsQueries = Depends(publications_queries),
) -> EntityLabelResponse:
    """Libellé d'une revue ou d'un éditeur par son identifiant.

    Sert à réafficher une pastille de facette restaurée depuis l'URL, qui porte l'identifiant seul : il est l'état canonique de la sélection.
    """
    return queries.resolve_entity_label(kind=kind, entity_id=entity_id)


@router.get("/export.csv")
def export_publications_csv(
    filters: Filters,
    sort: PublicationSort = Query("year_desc"),
    columns: str = Query(""),
    queries: PublicationsQueries = Depends(publications_queries),
) -> Response:
    """Export CSV des publications, fidèle au tableau affiché : mêmes filtres, et mêmes colonnes que celles listées dans `columns`."""
    csv_content = queries.export_publications_csv(
        filters=filters.to_filters(),
        sort=sort,
        columns=parse_str_csv(columns),
    )
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=publications.csv"},
    )


@router.get("/export-theses.csv")
def export_theses_csv(
    search: str = Query(""),
    lab_id: str = Query(""),
    year: str = Query(""),
    access: str = Query(""),
    source_filter: str = Query(""),
    doc_type: str = Query(""),
    sort: PublicationSort = Query("soutenance_desc"),
    queries: PublicationsQueries = Depends(publications_queries),
) -> Response:
    """Export CSV de la page thèses, aux mêmes filtres et au même tri que sa liste.

    La surface de filtres est plus étroite que celle des publications, et n'annonce que ce que l'export honore. Sans `doc_type`, il porte sur les thèses soutenues et en cours.
    """
    lab_ids, lab_none = _parse_lab_id(lab_id)
    filters = PublicationFilters(
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


@router.get("/duplicates/next", response_model=PubDuplicateNextResponse)
def next_duplicate_candidate(
    min_title_len: int = Query(30, ge=10),
    offset: int = Query(0, ge=0),
    queries: PublicationDuplicatesQueries = Depends(publication_duplicates_queries),
) -> PubDuplicateNextResponse:
    """Paire de publications candidate au dédoublonnage, à l'offset donné.

    Les candidats viennent de la requête `next_pub_duplicate`, qui rapproche les titres semblables, les années de publication voisines et les DOI convergents. `min_title_len` écarte les titres trop courts pour discriminer. L'offset laisse l'interface avancer paire par paire.
    """
    return queries.next_pub_duplicate(min_title_len=min_title_len, offset=offset)


@router.post("/duplicates/merge", response_model=PublicationMergeResponse)
def merge_duplicate_publications(
    body: MergePublications,
    conn: Connection = Depends(db_conn),
    repo: PublicationRepository = Depends(publication_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> PublicationMergeResponse:
    """Fusionne deux publications doublons.

    La cible est le plus petit des deux identifiants. Le sens de la fusion est sans portée durable : `refresh_from_sources` re-dérive toutes les métadonnées canoniques depuis l'union des `source_publications`, et cette union est la même dans un sens comme dans l'autre. Renvoie 400 sur deux identifiants égaux, 404 sur une publication introuvable, 409 sur deux DOI non-nuls distincts (`merge_publications`).
    """
    target_id, source_id = sorted((body.pub_id_a, body.pub_id_b))
    publication_commands.merge_publications(conn, target_id, source_id, repo=repo, audit_repo=audit)
    return PublicationMergeResponse(ok=True, target_id=target_id, source_id=source_id)


@router.post("/duplicates/mark-distinct", response_model=OkResponse)
def mark_publications_distinct(
    body: MarkDistinctPublications,
    conn: Connection = Depends(db_conn),
    repo: PublicationRepository = Depends(publication_repo),
    audit: AuditRepository = Depends(audit_repo),
) -> OkResponse:
    """Marque deux publications comme distinctes (non-doublon confirmé).

    Persiste l'annotation dans `distinct_publications` : la paire est écartée des prochaines revues de `/duplicates/next`. Renvoie 400 sur deux identifiants égaux (`mark_distinct`).
    """
    publication_commands.mark_distinct(
        conn, body.pub_id_a, body.pub_id_b, repo=repo, audit_repo=audit
    )
    return OkResponse()


@router.get("/{pub_id}", response_model=PublicationDetailResponse)
def get_publication(
    pub_id: int,
    queries: PublicationsQueries = Depends(publications_queries),
) -> PublicationDetailResponse:
    """Détail complet d'une publication."""
    detail = queries.get_publication_detail(pub_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Publication introuvable")
    return detail


@router.get("", response_model=PublicationListResponse)
def list_publications(
    filters: Filters,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: PublicationSort = Query("year_desc"),
    queries: PublicationsQueries = Depends(publications_queries),
) -> PublicationListResponse:
    """Liste paginée des publications, avec leurs sources, leurs laboratoires et leur revue.

    Les filtres se cumulent. `sort` accepte `year_desc`, `year_asc`, `title` et `cited_by`.
    """
    return queries.list_publications(
        filters=filters.to_filters(),
        page=page,
        per_page=per_page,
        sort=sort,
    )
