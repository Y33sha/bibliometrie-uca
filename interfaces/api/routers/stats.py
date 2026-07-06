"""Router /api/stats/* — délègue les requêtes au port StatsQueries."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query

from application.ports.api.entity_facet import EntityFacetResponse, EntityLabelResponse
from application.ports.api.stats_queries import (
    CollaborationsResponse,
    PivotResponse,
    PivotSchemaResponse,
    StatsFacetsResponse,
    StatsQueries,
)
from interfaces.api.deps import (
    get_apc_structure_ids_sync,
    stats_queries_sync,
)
from interfaces.api.filters import parse_int_csv, parse_str_csv

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/stats/years", response_model=list[int])
def available_years(
    queries: StatsQueries = Depends(stats_queries_sync),
) -> list[int]:
    """Liste des années présentes dans les publications validées (tri asc, restreint via la config `years_validated`)."""
    return queries.available_years()


@router.get("/api/stats/facets", response_model=StatsFacetsResponse)
def stats_facets(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: str = Query(""),
    journal_id: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> StatsFacetsResponse:
    """Facettes dynamiques : années, labos, oa_status, apc."""
    return queries.stats_facets(
        apc_structure_ids=get_apc_structure_ids_sync(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_ids=parse_int_csv(publisher_id),
        journal_ids=parse_int_csv(journal_id),
        oa_status=parse_str_csv(oa_status),
        has_apc=parse_str_csv(has_apc),
        doc_types=parse_str_csv(doc_type),
    )


@router.get("/api/stats/facets/entities", response_model=EntityFacetResponse)
def stats_entity_facet(
    kind: Literal["publisher", "journal"] = Query(...),
    entity_search: str = Query(""),
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: str = Query(""),
    journal_id: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> EntityFacetResponse:
    """Facette éditeur/revue contextuelle : N premières entités sous les filtres actifs (corrélées
    entre elles), avec décompte. `entity_search` recherche dans les noms d'entités."""
    return queries.stats_entity_facet(
        kind=kind,
        search=entity_search,
        apc_structure_ids=get_apc_structure_ids_sync(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_ids=parse_int_csv(publisher_id),
        journal_ids=parse_int_csv(journal_id),
        oa_status=parse_str_csv(oa_status),
        has_apc=parse_str_csv(has_apc),
        doc_types=parse_str_csv(doc_type),
    )


@router.get("/api/stats/facets/entity-label", response_model=EntityLabelResponse)
def stats_entity_label(
    kind: Literal["publisher", "journal"] = Query(...),
    entity_id: int = Query(...),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> EntityLabelResponse:
    """Libellé d'une entité (revue/éditeur) par id, pour réafficher une pastille de facette restaurée
    depuis l'URL (qui ne porte que l'id, état canonique de la sélection)."""
    return queries.resolve_entity_label(kind=kind, entity_id=entity_id)


@router.get("/api/stats/collaborations", response_model=CollaborationsResponse)
def collaborations(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: str = Query(""),
    journal_id: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> CollaborationsResponse:
    """Collaborations internationales : nombre de publications co-affiliées à chaque pays étranger,
    sous les filtres actifs. Source : la colonne `countries` des publications, hors pays domestique."""
    return queries.collaborations(
        apc_structure_ids=get_apc_structure_ids_sync(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_ids=parse_int_csv(publisher_id),
        journal_ids=parse_int_csv(journal_id),
        oa_status=parse_str_csv(oa_status),
        has_apc=parse_str_csv(has_apc),
        doc_types=parse_str_csv(doc_type),
    )


@router.get("/api/stats/pivot/schema", response_model=PivotSchemaResponse)
def pivot_schema(
    queries: StatsQueries = Depends(stats_queries_sync),
) -> PivotSchemaResponse:
    """Vocabulaire du pivot (dimensions groupables, mesures) dont l'interface tire ses sélecteurs."""
    return queries.pivot_schema()


@router.get("/api/stats/pivot", response_model=PivotResponse)
def pivot(
    measure: str = Query("pub_count"),
    group: str = Query(""),
    group2: str = Query(""),
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: str = Query(""),
    journal_id: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    queries: StatsQueries = Depends(stats_queries_sync),
) -> PivotResponse:
    """Agrégation générique : `measure` ventilée selon `group` (primaire) et `group2` (secondaire),
    sous les filtres. Clés validées contre le registre (400 si inconnues)."""
    groups = [g for g in (group, group2) if g]
    return queries.pivot(
        measure=measure,
        groups=groups,
        apc_structure_ids=get_apc_structure_ids_sync(),
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_ids=parse_int_csv(publisher_id),
        journal_ids=parse_int_csv(journal_id),
        oa_status=parse_str_csv(oa_status),
        has_apc=parse_str_csv(has_apc),
        doc_types=parse_str_csv(doc_type),
    )
