"""Query services pour /api/stats/* (router stats).

Le package est organisé par thème d'agrégat :
- `publishers` : `publisher_stats`
- `journals` : `journal_stats`
- `labs` : `stats_labs`
- `summary` : `stats_by_year`, `available_years`, `stats_facets`
- `_shared` : filtre APC + pagination partagés par tous les agrégats.

`PgStatsQueries` agrège les 7 fonctions sous le port `application.ports.stats_queries.StatsQueries`. Les fonctions libres retournent des dicts conformes au shape des DTOs ; la conversion vers Pydantic est faite ici à la sortie, pour garder les fonctions libres réutilisables hors API.
"""

from sqlalchemy import Connection

from application.ports.api.stats_queries import (
    ApcFacet,
    DocTypeFacet,
    JournalStatsResponse,
    JournalStatsRow,
    LabFacet,
    LabStatsResponse,
    LabStatsRow,
    OaFacet,
    PivotDimensionOut,
    PivotMeasureOut,
    PivotResponse,
    PivotSchemaResponse,
    PublisherStatsResponse,
    PublisherStatsRow,
    StatsFacetsResponse,
    StatsQueries,
    YearFacet,
    YearStatsRow,
)
from domain.stats.pivot import DIMENSIONS, MEASURES
from infrastructure.queries.api.stats.journals import journal_stats as _journal_stats
from infrastructure.queries.api.stats.labs import stats_labs as _stats_labs
from infrastructure.queries.api.stats.pivot import run_pivot as _run_pivot
from infrastructure.queries.api.stats.publishers import publisher_stats as _publisher_stats
from infrastructure.queries.api.stats.summary import (
    available_years as _available_years,
    stats_by_year as _stats_by_year,
    stats_facets as _stats_facets,
)


class PgStatsQueries(StatsQueries):
    """Adapter SA pour `application.ports.stats_queries.StatsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def publisher_stats(
        self,
        *,
        apc_structure_ids: list[int],
        lab_ids: list[int],
        years: list[int],
        oa_status: str,
        has_apc: str,
        doc_types: list[str],
        search: str,
        page: int,
        per_page: int,
        sort: str,
    ) -> PublisherStatsResponse:
        data = _publisher_stats(
            self._conn,
            apc_structure_ids=apc_structure_ids,
            lab_ids=lab_ids,
            years=years,
            oa_status=oa_status,
            has_apc=has_apc,
            doc_types=doc_types,
            search=search,
            page=page,
            per_page=per_page,
            sort=sort,
        )
        return PublisherStatsResponse(
            total=data["total"],
            page=data["page"],
            per_page=data["per_page"],
            pages=data["pages"],
            publishers=[PublisherStatsRow(**r) for r in data["publishers"]],
        )

    def journal_stats(
        self,
        *,
        apc_structure_ids: list[int],
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        oa_status: str,
        has_apc: str,
        doc_types: list[str],
        search: str,
        page: int,
        per_page: int,
        sort: str,
    ) -> JournalStatsResponse:
        data = _journal_stats(
            self._conn,
            apc_structure_ids=apc_structure_ids,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            oa_status=oa_status,
            has_apc=has_apc,
            doc_types=doc_types,
            search=search,
            page=page,
            per_page=per_page,
            sort=sort,
        )
        return JournalStatsResponse(
            total=data["total"],
            page=data["page"],
            per_page=data["per_page"],
            pages=data["pages"],
            journals=[JournalStatsRow(**r) for r in data["journals"]],
        )

    def stats_labs(
        self,
        *,
        apc_structure_ids: list[int],
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        journal_id: int | None,
        oa_status: str,
        has_apc: str,
        doc_types: list[str],
        page: int,
        per_page: int,
        sort: str,
    ) -> LabStatsResponse:
        data = _stats_labs(
            self._conn,
            apc_structure_ids=apc_structure_ids,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
            doc_types=doc_types,
            page=page,
            per_page=per_page,
            sort=sort,
        )
        return LabStatsResponse(
            total=data["total"],
            page=data["page"],
            per_page=data["per_page"],
            pages=data["pages"],
            labs=[LabStatsRow(**r) for r in data["labs"]],
        )

    def stats_by_year(
        self,
        *,
        apc_structure_ids: list[int],
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        journal_id: int | None,
        oa_status: str,
        has_apc: str,
        doc_types: list[str],
    ) -> list[YearStatsRow]:
        rows = _stats_by_year(
            self._conn,
            apc_structure_ids=apc_structure_ids,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
            doc_types=doc_types,
        )
        return [YearStatsRow(**r) for r in rows]


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
        publisher_id: int | None,
        journal_id: int | None,
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
                publisher_id=publisher_id,
                journal_id=journal_id,
                oa_status=oa_status,
                has_apc=has_apc,
                doc_types=doc_types,
            )
        )

    def stats_facets(
        self,
        *,
        apc_structure_ids: list[int],
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        journal_id: int | None,
        oa_status: str,
        has_apc: str,
        doc_types: list[str],
    ) -> StatsFacetsResponse:
        data = _stats_facets(
            self._conn,
            apc_structure_ids=apc_structure_ids,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
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
