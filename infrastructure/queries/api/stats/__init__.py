"""Query services pour /api/stats/* (router stats).

Le package est organisé par thème d'agrégat :
- `pivot` : `run_pivot` (agrégation générique) et le schéma du registre
- `collaborations` : `run_collaborations` (décompte des pays étrangers co-affiliés)
- `entity_facets` : `stats_entity_facet` (facette éditeur/revue contextuelle)
- `summary` : `available_years`, `stats_facets`
- `_shared` : périmètre de base, assemblage des filtres et filtre APC partagés par les agrégats.

`PgStatsQueries` agrège ces fonctions sous le port `application.ports.api.stats_queries.StatsQueries`. Les fonctions libres retournent des dicts conformes au shape des DTOs ; la conversion vers Pydantic est faite ici à la sortie, pour garder les fonctions libres réutilisables hors API.
"""

from typing import Literal

from sqlalchemy import Connection

from application.ports.api.entity_facet import (
    EntityFacetItem,
    EntityFacetResponse,
    EntityLabelResponse,
)
from application.ports.api.stats_queries import (
    ApcFacet,
    CollaborationsResponse,
    CountryCollaboration,
    DocTypeFacet,
    LabFacet,
    OaFacet,
    PivotDimensionOut,
    PivotMeasureOut,
    PivotResponse,
    PivotSchemaResponse,
    StatsFacetsResponse,
    StatsFilters,
    StatsQueries,
    YearFacet,
)
from domain.stats import DIMENSIONS, MEASURES
from infrastructure.queries.api.entity_labels import entity_label as _entity_label
from infrastructure.queries.api.stats.collaborations import (
    run_collaborations as _run_collaborations,
)
from infrastructure.queries.api.stats.entity_facets import stats_entity_facet as _stats_entity_facet
from infrastructure.queries.api.stats.pivot import run_pivot as _run_pivot
from infrastructure.queries.api.stats.summary import (
    available_years as _available_years,
    stats_facets as _stats_facets,
)
from infrastructure.queries.perimeter import get_persons_structure_ids_list


class PgStatsQueries(StatsQueries):
    """Adapter SA pour `application.ports.api.stats_queries.StatsQueries`.

    Le filtre `has_apc` classe un paiement d'APC en « interne » quand sa structure de budget appartient au périmètre `persons`. L'adapter résout ce périmètre là où il sert, comme `PgLaboratoriesQueries` : ses appelants n'ont pas à le connaître pour demander des statistiques.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def available_years(self) -> list[int]:
        return _available_years(self._conn)

    def collaborations(self, *, filters: StatsFilters) -> CollaborationsResponse:
        data = _run_collaborations(
            self._conn,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            filters=filters,
        )
        return CollaborationsResponse(
            rows=[CountryCollaboration(**r) for r in data["rows"]],
            international_count=data["international_count"],
            total_count=data["total_count"],
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
        return PivotResponse.model_validate(
            _run_pivot(
                self._conn,
                measure=measure,
                groups=groups,
                perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
                filters=filters,
            )
        )

    def stats_entity_facet(
        self,
        *,
        kind: Literal["publisher", "journal"],
        search: str,
        filters: StatsFilters,
    ) -> EntityFacetResponse:
        rows = _stats_entity_facet(
            self._conn,
            kind=kind,
            search=search,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            filters=filters,
        )
        return EntityFacetResponse(entities=[EntityFacetItem(**r) for r in rows])

    def resolve_entity_label(
        self, *, kind: Literal["publisher", "journal"], entity_id: int
    ) -> EntityLabelResponse:
        return EntityLabelResponse(label=_entity_label(self._conn, kind=kind, entity_id=entity_id))

    def stats_facets(self, *, filters: StatsFilters) -> StatsFacetsResponse:
        data = _stats_facets(
            self._conn,
            perimeter_structure_ids=get_persons_structure_ids_list(self._conn),
            filters=filters,
        )
        return StatsFacetsResponse(
            years=[YearFacet(**y) for y in data["years"]],
            labs=[LabFacet(**lab) for lab in data["labs"]],
            oa_statuses=[OaFacet(**o) for o in data["oa_statuses"]],
            apc=[ApcFacet(**a) for a in data["apc"]],
            doc_types=[DocTypeFacet(**d) for d in data["doc_types"]],
        )


__all__ = ["PgStatsQueries"]
