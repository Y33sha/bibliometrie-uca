"""Query services pour /api/stats/* (router stats).

Le package est organisé par thème d'agrégat :
- `publishers` : `publisher_stats`
- `journals` : `journal_stats`
- `labs` : `stats_labs`
- `summary` : `stats_by_year`, `stats_summary`, `available_years`, `stats_facets`
- `_shared` : filtre APC + pagination partagés par tous les agrégats.

`PgStatsQueries` agrège les 7 fonctions sous le port `application.ports.stats_queries.StatsQueries`. Les fonctions libres retournent des dicts conformes au shape des DTOs ; la conversion vers Pydantic est faite ici à la sortie, pour garder les fonctions libres réutilisables hors API.
"""

from sqlalchemy import Connection

from application.ports.api.stats_queries import (
    ApcFacet,
    JournalStatsResponse,
    JournalStatsRow,
    LabFacet,
    LabStatsResponse,
    LabStatsRow,
    OaFacet,
    PublisherStatsResponse,
    PublisherStatsRow,
    StatsFacetsResponse,
    StatsQueries,
    StatsSummary,
    YearFacet,
    YearStatsRow,
)
from infrastructure.queries.stats.journals import journal_stats as _journal_stats
from infrastructure.queries.stats.labs import stats_labs as _stats_labs
from infrastructure.queries.stats.publishers import publisher_stats as _publisher_stats
from infrastructure.queries.stats.summary import (
    available_years as _available_years,
)
from infrastructure.queries.stats.summary import (
    stats_by_year as _stats_by_year,
)
from infrastructure.queries.stats.summary import (
    stats_facets as _stats_facets,
)
from infrastructure.queries.stats.summary import (
    stats_summary as _stats_summary,
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
        )
        return [YearStatsRow(**r) for r in rows]

    def stats_summary(
        self,
        *,
        apc_structure_ids: list[int],
        lab_ids: list[int],
        years: list[int],
        publisher_id: int | None,
        journal_id: int | None,
        oa_status: str,
        has_apc: str,
    ) -> StatsSummary:
        return StatsSummary(
            **_stats_summary(
                self._conn,
                apc_structure_ids=apc_structure_ids,
                lab_ids=lab_ids,
                years=years,
                publisher_id=publisher_id,
                journal_id=journal_id,
                oa_status=oa_status,
                has_apc=has_apc,
            )
        )

    def available_years(self) -> list[int]:
        return _available_years(self._conn)

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
        )
        return StatsFacetsResponse(
            years=[YearFacet(**y) for y in data["years"]],
            labs=[LabFacet(**lab) for lab in data["labs"]],
            oa_statuses=[OaFacet(**o) for o in data["oa_statuses"]],
            apc=[ApcFacet(**a) for a in data["apc"]],
        )


__all__ = ["PgStatsQueries"]
