"""Router des publications : listes, facettes, détail, enregistrements sources et export. Sert `/api/publications/*`.

Les lectures passent par `PublicationsQueries`.

Les chemins littéraux — `/licenses`, `/facets`, `/export.csv`, `/export-theses.csv` — précèdent `/{publication_id}`, qui les accepterait sinon comme identifiant.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from domain.merge import MergedEntity
from domain.publications.doc_types import DOC_TYPES
from domain.publications.licenses import LICENSE_LABELS, License
from domain.publications.metadata import ACCESS_LEVELS, OA_STATUSES
from domain.sources.hal import HAL_DEPOSIT_STATUSES
from domain.sources.registry import SOURCE_FILTER_VALUES
from infrastructure.read_models._common import EntityFacetResponse, EntityKind
from infrastructure.read_models.publications.models import (
    EXPORT_COLUMNS,
    LICENSE_FILTER_VALUES,
    PublicationDetailResponse,
    PublicationFilters,
    PublicationListResponse,
    PublicationsFacetsResponse,
    PublicationSort,
    PublicationSourcesResponse,
    SuspectMergesResponse,
)
from infrastructure.read_models.publications.queries import PublicationsQueries
from interfaces.api.deps import entity_detail, publications_queries
from interfaces.api.entity_detail import EntityDetail
from interfaces.api.filters import (
    TOGGLE_VALUES,
    parse_int_csv,
    parse_lab_id,
    parse_ror_csv,
    parse_str_csv,
    parse_vocabulary_csv,
)
from interfaces.api.models import EnumOption, TotalCountResponse
from interfaces.api.params import SearchTerm
from interfaces.api.rate_limit import ExportSlot, export_rate_limit, export_slot, releasing

router = APIRouter(prefix="/api/publications", tags=["publications"])


@dataclass(frozen=True, slots=True)
class PublicationFilterParams:
    """Filtres de la page publications tels que la query string les porte.

    Injectés par `Depends()` : la liste, les deux facettes et l'export répondent aux mêmes
    questions sur le même ensemble, et les déclarer une fois les tient d'accord.

    Les valeurs multiples se séparent par des virgules. `lab_id` accepte la sentinelle `none`,
    qui retient les publications qu'aucun laboratoire ne signe, et se combine aux identifiants.
    """

    search: SearchTerm = ""
    lab_id: Annotated[str, Query()] = ""
    year: Annotated[str, Query()] = ""
    publisher_id: Annotated[int | None, Query()] = None
    serial_id: Annotated[int | None, Query()] = None
    monograph_id: Annotated[int | None, Query()] = None
    person_id: Annotated[int | None, Query()] = None
    author_id: Annotated[int | None, Query()] = None
    subject_id: Annotated[str, Query()] = ""
    access: Annotated[str, Query()] = ""
    oa_status: Annotated[str, Query()] = ""
    license: Annotated[str, Query()] = ""
    source_filter: Annotated[str, Query()] = ""
    doc_type: Annotated[str, Query()] = ""
    excluded_doc_type: Annotated[str, Query()] = ""
    is_corresponding: Annotated[str, Query()] = ""
    has_apc: Annotated[str, Query()] = ""
    country: Annotated[str, Query()] = ""
    language: Annotated[str, Query()] = ""
    hal_status: Annotated[str, Query()] = ""
    in_perimeter: Annotated[str, Query()] = ""
    partner_ror: Annotated[str, Query()] = ""

    def to_filters(self) -> PublicationFilters:
        """Traduit la query string en filtres de la lecture."""
        lab_ids, lab_none = parse_lab_id(self.lab_id)
        return PublicationFilters(
            search=self.search,
            lab_ids=lab_ids,
            lab_none=lab_none,
            years=parse_int_csv(self.year, param="year"),
            publisher_id=self.publisher_id,
            serial_id=self.serial_id,
            monograph_id=self.monograph_id,
            person_id=self.person_id,
            author_id=self.author_id,
            subject_ids=parse_int_csv(self.subject_id, param="subject_id"),
            access=parse_vocabulary_csv(self.access, allowed=ACCESS_LEVELS, param="access"),
            oa_status=parse_vocabulary_csv(self.oa_status, allowed=OA_STATUSES, param="oa_status"),
            license=parse_vocabulary_csv(
                self.license, allowed=LICENSE_FILTER_VALUES, param="license"
            ),
            source_values=parse_vocabulary_csv(
                self.source_filter, allowed=SOURCE_FILTER_VALUES, param="source_filter"
            ),
            doc_types=parse_vocabulary_csv(self.doc_type, allowed=DOC_TYPES, param="doc_type"),
            excluded_types=parse_vocabulary_csv(
                self.excluded_doc_type, allowed=DOC_TYPES, param="excluded_doc_type"
            ),
            is_corresponding=parse_vocabulary_csv(
                self.is_corresponding, allowed=TOGGLE_VALUES, param="is_corresponding"
            ),
            has_apc=parse_vocabulary_csv(self.has_apc, allowed=TOGGLE_VALUES, param="has_apc"),
            country_values=parse_str_csv(self.country),
            language_codes=parse_str_csv(self.language),
            hal_status_values=parse_vocabulary_csv(
                self.hal_status, allowed=HAL_DEPOSIT_STATUSES, param="hal_status"
            ),
            in_perimeter=parse_vocabulary_csv(
                self.in_perimeter, allowed=TOGGLE_VALUES, param="in_perimeter"
            ),
            partner_rors=parse_ror_csv(self.partner_ror, param="partner_ror"),
        )


Filters = Annotated[PublicationFilterParams, Depends()]


@router.get("/licenses", response_model=list[EnumOption])
def list_licenses() -> list[EnumOption]:
    """Licences d'une publication avec leur libellé français, dans l'ordre de `domain.publications.licenses.License`."""
    return [EnumOption(value=v, label_fr=LICENSE_LABELS[v]) for v in License]


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


def _csv_stream(chunks: Iterator[str], *, filename: str, slot: ExportSlot) -> StreamingResponse:
    """Emballe les blocs d'un export en réponse de téléchargement, envoyés au fil de leur production.

    La mémoire tenue pendant l'envoi vaut un bloc à la fois, plus les lignes que la requête a ramenées.

    Le droit d'export passe au flux, qui le rend quand le parcours s'achève : la mémoire reste prise tant que le corps part, et le cycle de vie des dépendances s'achève avant.

    Le statut et les en-têtes partent avec le premier bloc : une erreur survenant pendant l'envoi ferme la connexion sur un fichier tronqué, sous un statut 200. Les lignes sont en mémoire à ce stade, la requête s'étant exécutée avant que la réponse ne commence.
    """
    return StreamingResponse(
        releasing(chunks, slot),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export.csv")
def export_publications_csv(
    filters: Filters,
    sort: PublicationSort = Query("year_desc"),
    columns: str = Query(""),
    queries: PublicationsQueries = Depends(publications_queries),
    _rate_limit: None = Depends(export_rate_limit),
    slot: ExportSlot = Depends(export_slot),
) -> StreamingResponse:
    """Export CSV des publications, fidèle au tableau affiché : mêmes filtres, et mêmes colonnes que celles listées dans `columns`.

    Le nombre de lignes est plafonné, et la fréquence des demandes l'est aussi (429 au-delà) : l'export balaie la table sous les seuls filtres reçus, et rien n'oblige un appelant à s'arrêter."""
    return _csv_stream(
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
    return _csv_stream(
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


@router.get("", response_model=PublicationListResponse)
def list_publications(
    filters: Filters,
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
