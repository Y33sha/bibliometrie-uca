"""Port : lectures stats (consommé par le router stats).

Implémenté par `infrastructure.queries.stats.PgStatsQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4.
"""

from typing import Literal, Protocol

from pydantic import BaseModel


class OaCounts(BaseModel):
    """Agrégats communs aux lignes de stats (éditeurs, revues, labos).

    `apc_uca` est toujours numérique (coalescé à 0 côté SQL).
    """

    pub_count: int
    apc_uca: float
    gold: int
    diamond: int
    hybrid: int
    bronze: int
    green: int
    closed: int
    unknown: int


class PublisherStatsRow(OaCounts):
    publisher_id: int
    publisher_name: str
    journal_count: int


class JournalStatsRow(OaCounts):
    journal_id: int
    journal_title: str
    issn: str | None
    eissn: str | None
    publisher_name: str | None
    is_predatory: bool
    apc_amount: float | None


class LabStatsRow(OaCounts):
    lab_id: int
    lab_acronym: str | None
    lab_name: str


class PublisherStatsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    publishers: list[PublisherStatsRow]


class JournalStatsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    journals: list[JournalStatsRow]


class LabStatsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    labs: list[LabStatsRow]


class YearStatsRow(BaseModel):
    """Ventilation d'une année : pub_count + détail OA."""

    pub_year: int
    pub_count: int
    gold: int
    diamond: int
    hybrid: int
    bronze: int
    green: int
    closed: int
    unknown: int


class StatsSummary(BaseModel):
    """Totaux globaux pour la page stats.

    Pas de champ `diamond` — le résumé remonte gold/hybrid/green/bronze/closed/unknown uniquement (diamond non distingué côté summary SQL).
    """

    total_pubs: int
    gold: int
    hybrid: int
    green: int
    bronze: int
    closed: int
    unknown: int
    publisher_count: int
    journal_count: int


class YearFacet(BaseModel):
    value: int
    count: int


class LabFacet(BaseModel):
    value: int
    label: str
    count: int


class OaFacet(BaseModel):
    value: str
    count: int


class ApcFacet(BaseModel):
    value: Literal["uca", "non_uca", "none"]
    text: str
    count: int


class StatsFacetsResponse(BaseModel):
    years: list[YearFacet]
    labs: list[LabFacet]
    oa_statuses: list[OaFacet]
    apc: list[ApcFacet]


class StatsQueries(Protocol):
    """Lectures pour /api/stats/*."""

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
    ) -> PublisherStatsResponse: ...

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
    ) -> JournalStatsResponse: ...

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
    ) -> LabStatsResponse: ...

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
    ) -> list[YearStatsRow]: ...

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
    ) -> StatsSummary: ...

    def available_years(self) -> list[int]: ...

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
    ) -> StatsFacetsResponse: ...
