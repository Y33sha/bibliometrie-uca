"""Router des agrégats des tableaux de bord, servis par le port `StatsQueries`. Sert `/api/stats/*`."""

from fastapi import APIRouter, Depends, Query

from application.ports.api._common import EntityFacetResponse, EntityKind
from application.ports.api.stats_queries import (
    CollaborationsResponse,
    PivotResponse,
    PivotSchemaResponse,
    StatsFacetsResponse,
    StatsFilters,
    StatsQueries,
)
from domain.errors import ValidationError
from domain.publications.doc_types import DOC_TYPES
from domain.publications.metadata import OA_STATUSES
from interfaces.api.deps import stats_queries
from interfaces.api.filters import parse_int_csv, parse_str_csv, parse_vocabulary_csv

router = APIRouter(prefix="/api/stats", tags=["stats"])


def stats_filters(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: str = Query(""),
    journal_id: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
) -> StatsFilters:
    """Dépendance : assemble les filtres communs des endpoints stats depuis les query params, en listes séparées par des virgules.

    `oa_status` et `doc_type` sont pris dans leur vocabulaire fermé (mêmes valeurs que la liste des publications) ; une valeur inconnue rend 422. `has_apc` est une facette multi-sélection (`uca` / `non_uca` / `none`) non restreinte ici.
    """
    return StatsFilters(
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_ids=parse_int_csv(publisher_id),
        journal_ids=parse_int_csv(journal_id),
        oa_status=parse_vocabulary_csv(oa_status, allowed=OA_STATUSES, param="oa_status"),
        has_apc=parse_str_csv(has_apc),
        doc_types=parse_vocabulary_csv(doc_type, allowed=DOC_TYPES, param="doc_type"),
    )


@router.get("/facets", response_model=StatsFacetsResponse)
def stats_facets(
    filters: StatsFilters = Depends(stats_filters),
    queries: StatsQueries = Depends(stats_queries),
) -> StatsFacetsResponse:
    """Décomptes par option des facettes des tableaux de bord.

    Chaque facette écarte sa propre dimension de la clause WHERE : son décompte annonce le nombre de publications atteignables si l'option était cochée ou décochée.
    """
    return queries.stats_facets(filters=filters)


@router.get("/facets/entities", response_model=EntityFacetResponse)
def stats_entity_facet(
    kind: EntityKind = Query(...),
    entity_search: str = Query(""),
    filters: StatsFilters = Depends(stats_filters),
    queries: StatsQueries = Depends(stats_queries),
) -> EntityFacetResponse:
    """Facette contextuelle des éditeurs ou des revues : les premières entités sous les filtres actifs, avec leur décompte.

    Les entités sont corrélées entre elles. `entity_search` cherche dans leurs noms.
    """
    return queries.stats_entity_facet(kind=kind, search=entity_search, filters=filters)


@router.get("/collaborations", response_model=CollaborationsResponse)
def collaborations(
    filters: StatsFilters = Depends(stats_filters),
    queries: StatsQueries = Depends(stats_queries),
) -> CollaborationsResponse:
    """Collaborations internationales : le nombre de publications co-affiliées à chaque pays étranger, sous les filtres actifs.

    Le décompte se lit dans la colonne `countries` des publications, le pays domestique écarté.
    """
    return queries.collaborations(filters=filters)


@router.get("/pivot/schema", response_model=PivotSchemaResponse)
def pivot_schema(
    queries: StatsQueries = Depends(stats_queries),
) -> PivotSchemaResponse:
    """Vocabulaire du pivot (dimensions groupables, mesures) dont l'interface tire ses sélecteurs."""
    return queries.pivot_schema()


@router.get("/pivot", response_model=PivotResponse)
def pivot(
    measure: str = Query("pub_count"),
    group: str = Query(""),
    group2: str = Query(""),
    filters: StatsFilters = Depends(stats_filters),
    queries: StatsQueries = Depends(stats_queries),
) -> PivotResponse:
    """Agrégation générique : `measure` ventilée selon `group` puis `group2`, sous les filtres actifs.

    Les trois clés sont validées contre le registre des mesures et des ventilations ; une clé inconnue, une ventilation non groupable ou répétée donnent un 400, comme `group2` fourni sans `group`.
    """
    if group2 and not group:
        raise ValidationError("Une seconde ventilation exige la première : `group2` sans `group`")
    groups = [g for g in (group, group2) if g]
    return queries.pivot(measure=measure, groups=groups, filters=filters)
