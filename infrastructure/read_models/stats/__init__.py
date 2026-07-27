"""Query services pour /api/stats/* (router stats).

Le package est organisé par thème d'agrégat :
- `pivot` : `run_pivot` (agrégation générique) et le schéma du registre
- `collaborations` : `run_collaborations` (décompte des pays étrangers co-affiliés)
- `entity_facets` : `stats_entity_facet` (facette éditeur/revue contextuelle)
- `summary` : `stats_facets`
- `_shared` : périmètre de base, assemblage des filtres et filtre APC partagés par les agrégats.

`PgStatsQueries` agrège ces fonctions sous le port `application.ports.read_models.stats_queries.StatsQueries`. Les fonctions libres retournent des dicts conformes au shape des DTOs ; la conversion vers Pydantic est faite ici à la sortie, pour garder les fonctions libres réutilisables hors API.
"""

from sqlalchemy import Connection

from application.ports.read_models._common import (
    EntityFacetResponse,
    EntityKind,
)
from application.ports.read_models.stats_queries import (
    CollaborationsResponse,
    PivotDimensionOut,
    PivotMeasureOut,
    PivotResponse,
    PivotSchemaResponse,
    StatsFacetsResponse,
    StatsFilters,
    StatsQueries,
)
from domain.stats import DIMENSIONS, MEASURES
from infrastructure.queries.perimeter import get_persons_structure_ids_list
from infrastructure.read_models.stats.collaborations import (
    run_collaborations as _run_collaborations,
)
from infrastructure.read_models.stats.entity_facets import stats_entity_facet as _stats_entity_facet
from infrastructure.read_models.stats.pivot import run_pivot as _run_pivot
from infrastructure.read_models.stats.summary import (
    stats_facets as _stats_facets,
)


class PgStatsQueries(StatsQueries):
    """Adapter SA pour `application.ports.read_models.stats_queries.StatsQueries`.

    Le filtre `has_apc` classe un paiement d'APC en « interne » quand sa structure de budget appartient au périmètre `persons`. L'adapter résout ce périmètre là où il sert : ses appelants n'ont pas à le connaître pour demander des statistiques.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def collaborations(self, *, filters: StatsFilters) -> CollaborationsResponse:
        return _run_collaborations(
            self._conn,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            filters=filters,
        )

    def pivot_schema(self) -> PivotSchemaResponse:
        return PivotSchemaResponse(
            dimensions=[
                PivotDimensionOut(
                    key=d.key,
                    label=d.label,
                    cardinality=d.cardinality,
                    ordinal=d.ordinal,
                    groupable=d.groupable,
                    comparable=d.comparable,
                    filterable=d.filterable,
                )
                for d in DIMENSIONS.values()
            ],
            measures=[PivotMeasureOut(key=m.key, label=m.label) for m in MEASURES.values()],
        )

    def pivot(self, *, measure: str, groups: list[str], filters: StatsFilters) -> PivotResponse:
        return _run_pivot(
            self._conn,
            measure=measure,
            groups=groups,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            filters=filters,
        )

    def stats_entity_facet(
        self,
        *,
        kind: EntityKind,
        search: str,
        filters: StatsFilters,
    ) -> EntityFacetResponse:
        return EntityFacetResponse(
            entities=_stats_entity_facet(
                self._conn,
                kind=kind,
                search=search,
                perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
                filters=filters,
            )
        )

    def stats_facets(self, *, filters: StatsFilters) -> StatsFacetsResponse:
        return _stats_facets(
            self._conn,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            filters=filters,
        )


__all__ = ["PgStatsQueries"]
