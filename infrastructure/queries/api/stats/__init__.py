"""Query services pour /api/stats/* (router stats).

Le package est organisé par thème d'agrégat :
- `pivot` : `run_pivot` (agrégation générique) et le schéma du registre
- `summary` : `available_years`, `stats_facets`
- `_shared` : filtre APC partagé par les agrégats.

`PgStatsQueries` agrège ces fonctions sous le port `application.ports.stats_queries.StatsQueries`. Les fonctions libres retournent des dicts conformes au shape des DTOs ; la conversion vers Pydantic est faite ici à la sortie, pour garder les fonctions libres réutilisables hors API.
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
    DocTypeFacet,
    LabFacet,
    OaFacet,
    PivotDimensionOut,
    PivotMeasureOut,
    PivotResponse,
    PivotSchemaResponse,
    StatsFacetsResponse,
    StatsQueries,
    YearFacet,
)
from domain.stats.pivot import DIMENSIONS, MEASURES
from infrastructure.queries.api.entity_labels import entity_label as _entity_label
from infrastructure.queries.api.stats.entity_facets import stats_entity_facet as _stats_entity_facet
from infrastructure.queries.api.stats.pivot import run_pivot as _run_pivot
from infrastructure.queries.api.stats.summary import (
    available_years as _available_years,
    stats_facets as _stats_facets,
)


class PgStatsQueries(StatsQueries):
    """Adapter SA pour `application.ports.stats_queries.StatsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def available_years(self) -> list[int]:
        return _available_years(self._conn)

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

    def pivot(
        self,
        *,
        measure: str,
        groups: list[str],
        apc_structure_ids: list[int],
        lab_ids: list[int],
        years: list[int],
        publisher_ids: list[int],
        journal_ids: list[int],
        oa_status: str,
        has_apc: str,
        doc_types: list[str],
    ) -> PivotResponse:
        return PivotResponse.model_validate(
            _run_pivot(
                self._conn,
                measure=measure,
                groups=groups,
                apc_structure_ids=apc_structure_ids,
                lab_ids=lab_ids,
                years=years,
                publisher_ids=publisher_ids,
                journal_ids=journal_ids,
                oa_status=oa_status,
                has_apc=has_apc,
                doc_types=doc_types,
            )
        )

    def stats_entity_facet(
        self,
        *,
        kind: Literal["publisher", "journal"],
        search: str,
        apc_structure_ids: list[int],
        lab_ids: list[int],
        years: list[int],
        publisher_ids: list[int],
        journal_ids: list[int],
        oa_status: str,
        has_apc: str,
        doc_types: list[str],
    ) -> EntityFacetResponse:
        rows = _stats_entity_facet(
            self._conn,
            kind=kind,
            search=search,
            apc_structure_ids=apc_structure_ids,
            lab_ids=lab_ids,
            years=years,
            publisher_ids=publisher_ids,
            journal_ids=journal_ids,
            oa_status=oa_status,
            has_apc=has_apc,
            doc_types=doc_types,
        )
        return EntityFacetResponse(entities=[EntityFacetItem(**r) for r in rows])

    def resolve_entity_label(
        self, *, kind: Literal["publisher", "journal"], entity_id: int
    ) -> EntityLabelResponse:
        return EntityLabelResponse(label=_entity_label(self._conn, kind=kind, entity_id=entity_id))

    def stats_facets(
        self,
        *,
        apc_structure_ids: list[int],
        lab_ids: list[int],
        years: list[int],
        publisher_ids: list[int],
        journal_ids: list[int],
        oa_status: str,
        has_apc: str,
        doc_types: list[str],
    ) -> StatsFacetsResponse:
        data = _stats_facets(
            self._conn,
            apc_structure_ids=apc_structure_ids,
            lab_ids=lab_ids,
            years=years,
            publisher_ids=publisher_ids,
            journal_ids=journal_ids,
            oa_status=oa_status,
            has_apc=has_apc,
            doc_types=doc_types,
        )
        return StatsFacetsResponse(
            years=[YearFacet(**y) for y in data["years"]],
            labs=[LabFacet(**lab) for lab in data["labs"]],
            oa_statuses=[OaFacet(**o) for o in data["oa_statuses"]],
            apc=[ApcFacet(**a) for a in data["apc"]],
            doc_types=[DocTypeFacet(**d) for d in data["doc_types"]],
        )


__all__ = ["PgStatsQueries"]
