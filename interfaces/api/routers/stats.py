"""Router /api/stats/* — les agrégats des tableaux de bord, servis par le port `StatsQueries`."""

from dataclasses import asdict, dataclass
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
    get_apc_structure_ids,
    stats_queries,
)
from interfaces.api.filters import parse_int_csv, parse_str_csv

router = APIRouter()


@dataclass(frozen=True)
class StatsFilters:
    """Filtres communs à tous les endpoints de statistiques, lus des paramètres de requête en valeurs séparées par des virgules.

    Les noms des champs reprennent ceux des méthodes de `StatsQueries`, ce qui permet de les passer en `**asdict(...)`.
    """

    apc_structure_ids: list[int]
    lab_ids: list[int]
    years: list[int]
    publisher_ids: list[int]
    journal_ids: list[int]
    oa_status: list[str]
    has_apc: list[str]
    doc_types: list[str]


def stats_filters(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: str = Query(""),
    journal_id: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    doc_type: str = Query(""),
    apc_structure_ids: list[int] = Depends(get_apc_structure_ids),
) -> StatsFilters:
    """Dépendance : assemble les filtres communs des endpoints stats depuis les query params."""
    return StatsFilters(
        apc_structure_ids=apc_structure_ids,
        lab_ids=parse_int_csv(lab_id),
        years=parse_int_csv(year),
        publisher_ids=parse_int_csv(publisher_id),
        journal_ids=parse_int_csv(journal_id),
        oa_status=parse_str_csv(oa_status),
        has_apc=parse_str_csv(has_apc),
        doc_types=parse_str_csv(doc_type),
    )


@router.get("/api/stats/years", response_model=list[int])
def available_years(
    queries: StatsQueries = Depends(stats_queries),
) -> list[int]:
    """Liste des années présentes dans les publications validées (tri asc, restreint via la config `years_validated`)."""
    return queries.available_years()


@router.get("/api/stats/facets", response_model=StatsFacetsResponse)
def stats_facets(
    filters: StatsFilters = Depends(stats_filters),
    queries: StatsQueries = Depends(stats_queries),
) -> StatsFacetsResponse:
    """Facettes dynamiques : années, labos, oa_status, apc."""
    return queries.stats_facets(**asdict(filters))


@router.get("/api/stats/facets/entities", response_model=EntityFacetResponse)
def stats_entity_facet(
    kind: Literal["publisher", "journal"] = Query(...),
    entity_search: str = Query(""),
    filters: StatsFilters = Depends(stats_filters),
    queries: StatsQueries = Depends(stats_queries),
) -> EntityFacetResponse:
    """Facette contextuelle des éditeurs ou des revues : les premières entités sous les filtres actifs, avec leur décompte.

    Les entités sont corrélées entre elles. `entity_search` cherche dans leurs noms.
    """
    return queries.stats_entity_facet(kind=kind, search=entity_search, **asdict(filters))


@router.get("/api/stats/facets/entity-label", response_model=EntityLabelResponse)
def stats_entity_label(
    kind: Literal["publisher", "journal"] = Query(...),
    entity_id: int = Query(...),
    queries: StatsQueries = Depends(stats_queries),
) -> EntityLabelResponse:
    """Libellé d'une revue ou d'un éditeur par son identifiant.

    Sert à réafficher une pastille de facette restaurée depuis l'URL, qui porte l'identifiant seul : il est l'état canonique de la sélection.
    """
    return queries.resolve_entity_label(kind=kind, entity_id=entity_id)


@router.get("/api/stats/collaborations", response_model=CollaborationsResponse)
def collaborations(
    filters: StatsFilters = Depends(stats_filters),
    queries: StatsQueries = Depends(stats_queries),
) -> CollaborationsResponse:
    """Collaborations internationales : le nombre de publications co-affiliées à chaque pays étranger, sous les filtres actifs.

    Le décompte se lit dans la colonne `countries` des publications, le pays domestique écarté.
    """
    return queries.collaborations(**asdict(filters))


@router.get("/api/stats/pivot/schema", response_model=PivotSchemaResponse)
def pivot_schema(
    queries: StatsQueries = Depends(stats_queries),
) -> PivotSchemaResponse:
    """Vocabulaire du pivot (dimensions groupables, mesures) dont l'interface tire ses sélecteurs."""
    return queries.pivot_schema()


@router.get("/api/stats/pivot", response_model=PivotResponse)
def pivot(
    measure: str = Query("pub_count"),
    group: str = Query(""),
    group2: str = Query(""),
    filters: StatsFilters = Depends(stats_filters),
    queries: StatsQueries = Depends(stats_queries),
) -> PivotResponse:
    """Agrégation générique : `measure` ventilée selon `group` puis `group2`, sous les filtres actifs.

    Les trois clés sont validées contre le registre des mesures et des ventilations ; une clé inconnue donne un 400.
    """
    groups = [g for g in (group, group2) if g]
    return queries.pivot(measure=measure, groups=groups, **asdict(filters))
