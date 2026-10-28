"""Router des publications : listes, facettes, détail, enregistrements sources et export. Sert `/api/publications/*`.

Les lectures passent par `PublicationsQueries`.

Les chemins littéraux — `/licenses`, `/facets`, `/export.csv`, `/export-theses.csv` — précèdent `/{publication_id}`, qui les accepterait sinon comme identifiant.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from application.services.publication_merge import PublicationMergeService
from domain.merge import MergedEntity
from domain.publications.doc_types import DOC_TYPES
from domain.publications.licenses import LICENSE_LABELS, License
from domain.publications.metadata import ACCESS_LEVELS
from domain.sources.registry import SOURCE_FILTER_VALUES
from infrastructure.read_models._common import EntityFacetResponse, EntityKind
from infrastructure.read_models.publications.models import (
    EXPORT_COLUMNS,
    PublicationDetailResponse,
    PublicationFilters,
    PublicationListResponse,
    PublicationsFacetsResponse,
    PublicationSort,
    PublicationSourcesResponse,
    SuspectMergesResponse,
)
from infrastructure.read_models.publications.queries import PublicationsQueries
from interfaces.api.csv_export import csv_response
from interfaces.api.deps import entity_detail, publication_merge_service, publications_queries
from interfaces.api.entity_detail import EntityDetail
from interfaces.api.filters import (
    parse_int_csv,
    parse_lab_id,
    parse_vocabulary_csv,
)
from interfaces.api.models import (
    EnumOption,
    PublicationMergeRequest,
    PublicationMergeResult,
    TotalCountResponse,
)
from interfaces.api.params import SearchTerm
from interfaces.api.publication_filters import ListFilters
from interfaces.api.rate_limit import ExportSlot, export_rate_limit, export_slot

router = APIRouter(prefix="/api/publications", tags=["publications"])


@router.get("/licenses", response_model=list[EnumOption])
def list_licenses() -> list[EnumOption]:
    """Licences d'une publication avec leur libellé français, dans l'ordre de `domain.publications.licenses.License`."""
    return [EnumOption(value=v, label_fr=LICENSE_LABELS[v]) for v in License]


@router.get("/facets", response_model=PublicationsFacetsResponse)
def publications_facets(
    filters: ListFilters,
    queries: PublicationsQueries = Depends(publications_queries),
) -> PublicationsFacetsResponse:
    """Décomptes par option des facettes de la liste des publications.

    Chaque facette écarte sa propre dimension de la clause WHERE : son décompte annonce le nombre de publications atteignables si l'option était cochée ou décochée.
    """
    return queries.publications_facets(filters=filters.to_filters())


@router.get("/facets/entities", response_model=EntityFacetResponse)
def publications_entity_facet(
    filters: ListFilters,
    kind: EntityKind = Query(...),
    entity_search: SearchTerm = "",
    queries: PublicationsQueries = Depends(publications_queries),
) -> EntityFacetResponse:
    """Facette contextuelle des éditeurs, des revues, des auteurs ou des sujets : les premières entités sous les filtres actifs, avec leur décompte.

    Les entités sont corrélées entre elles. `entity_search` cherche dans leurs noms, là où `search` filtre les publications sur leur titre et leurs sujets.
    """
    return queries.publications_entity_facet(
        kind=kind,
        search=entity_search,
        filters=filters.to_filters(),
    )


@router.get("/export.csv")
def export_publications_csv(
    filters: ListFilters,
    sort: PublicationSort = Query("year_desc"),
    columns: str = Query(""),
    queries: PublicationsQueries = Depends(publications_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV des publications, fidèle au tableau affiché : mêmes filtres, et mêmes colonnes que celles listées dans `columns`.

    Le nombre de lignes est plafonné, et la fréquence des demandes l'est aussi (429 au-delà) : l'export balaie la table sous les seuls filtres reçus, et rien n'oblige un appelant à s'arrêter."""
    return csv_response(
        queries.export_publications_csv(
            filters=filters.to_filters(),
            sort=sort,
            columns=parse_vocabulary_csv(columns, allowed=EXPORT_COLUMNS, param="columns"),
        ),
        filename="publications.csv",
        slot=slot,
    )


@router.get("/export-theses.csv")
def export_theses_csv(
    search: SearchTerm = "",
    lab_id: str = Query(""),
    year: str = Query(""),
    access: str = Query(""),
    source_filter: str = Query(""),
    doc_type: str = Query(""),
    sort: PublicationSort = Query("soutenance_desc"),
    queries: PublicationsQueries = Depends(publications_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV de la page thèses, aux mêmes filtres et au même tri que sa liste.

    Plafonné en nombre de lignes et en fréquence, comme l'export des publications.

    La surface de filtres est plus étroite que celle des publications, et n'annonce que ce que l'export honore. Sans `doc_type`, il porte sur les thèses soutenues et en cours.
    """
    lab_ids, lab_none = parse_lab_id(lab_id)
    filters = PublicationFilters(
        search=search,
        lab_ids=lab_ids,
        lab_none=lab_none,
        years=parse_int_csv(year, param="year"),
        access=parse_vocabulary_csv(access, allowed=ACCESS_LEVELS, param="access"),
        source_values=parse_vocabulary_csv(
            source_filter, allowed=SOURCE_FILTER_VALUES, param="source_filter"
        ),
        doc_types=parse_vocabulary_csv(doc_type, allowed=DOC_TYPES, param="doc_type")
        or ["thesis", "ongoing_thesis"],
    )
    return csv_response(
        queries.export_theses_csv(filters=filters, sort=sort), filename="theses.csv", slot=slot
    )


@router.get("/suspect-merges/count", response_model=TotalCountResponse)
def suspect_merges_count(
    queries: PublicationsQueries = Depends(publications_queries),
) -> TotalCountResponse:
    """Compteur de l'onglet « Fusions suspectes » (badge)."""
    return TotalCountResponse(total=queries.suspect_merges_count())


@router.get("/suspect-merges", response_model=SuspectMergesResponse)
def suspect_merges(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    queries: PublicationsQueries = Depends(publications_queries),
) -> SuspectMergesResponse:
    """Publications dont moins de la moitié des contributions sources d'auteur ont un correspondant dans un autre enregistrement source, paginées."""
    return queries.suspect_merges(page=page, per_page=per_page)


@router.get("/{publication_id}", response_model=PublicationDetailResponse)
def get_publication(
    publication_id: int,
    queries: PublicationsQueries = Depends(publications_queries),
    detail: EntityDetail = Depends(entity_detail(MergedEntity.PUBLICATION)),
) -> PublicationDetailResponse:
    """Détail complet d'une publication."""
    return detail.found(queries.get_publication_detail(publication_id))


@router.get("/{publication_id}/sources", response_model=PublicationSourcesResponse)
def get_publication_sources(
    publication_id: int,
    queries: PublicationsQueries = Depends(publications_queries),
) -> PublicationSourcesResponse:
    """Métadonnées de chaque enregistrement source de la publication, toutes sources confondues."""
    sources = queries.get_publication_sources(publication_id)
    if sources is None:
        raise HTTPException(status_code=404, detail="Publication introuvable")
    return sources


@router.post("/{publication_id}/merge-preview", response_model=PublicationMergeResult)
def preview_merge(
    publication_id: int,
    body: PublicationMergeRequest,
    merges: PublicationMergeService = Depends(publication_merge_service),
) -> PublicationMergeResult:
    """Résultat qu'aurait la fusion manuelle des deux publications : publication conservée, conflits d'auteurs.

    L'aperçu applique réellement la fusion dans un `SAVEPOINT` annulé ensuite, donc aucune écriture ne survit. Il est en POST pour passer par la garde d'authentification des méthodes d'écriture. Renvoie 422 sur deux identifiants égaux ou deux DOI distincts, 404 sur une publication introuvable.
    """
    outcome = merges.preview_merge(publication_id, body.other_id)
    return PublicationMergeResult(
        publication_id=outcome.publication_id, conflicts=outcome.conflicts
    )


@router.post("/{publication_id}/merge", response_model=PublicationMergeResult)
def merge(
    publication_id: int,
    body: PublicationMergeRequest,
    merges: PublicationMergeService = Depends(publication_merge_service),
) -> PublicationMergeResult:
    """Fusionne manuellement les deux publications. La réconciliation relit ce verdict à chaque passage du pipeline.

    Renvoie la publication conservée, et le nombre de contributions laissées sans personne parce que leurs contributions sources désignaient deux personnes. Renvoie 422 sur deux identifiants égaux ou deux DOI distincts, 404 sur une publication introuvable.
    """
    outcome = merges.merge(publication_id, body.other_id)
    return PublicationMergeResult(
        publication_id=outcome.publication_id, conflicts=outcome.conflicts
    )


@router.get("", response_model=PublicationListResponse)
def list_publications(
    filters: ListFilters,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: PublicationSort = Query("year_desc"),
    queries: PublicationsQueries = Depends(publications_queries),
) -> PublicationListResponse:
    """Liste paginée des publications, avec leurs sources, leurs laboratoires et leur revue.

    Les filtres se cumulent. `sort` combine un champ — année, titre, APC, date de soutenance ou d'inscription — et un sens (`_asc` / `_desc`).
    """
    return queries.list_publications(
        filters=filters.to_filters(),
        page=page,
        per_page=per_page,
        sort=sort,
    )
