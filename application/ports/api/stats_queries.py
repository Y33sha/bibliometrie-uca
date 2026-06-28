"""Port : lectures stats (consommé par le router stats).

Implémenté par `infrastructure.queries.api.stats.PgStatsQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4.
"""

from typing import Literal, Protocol

from pydantic import BaseModel


class YearStatsRow(BaseModel):
    """Ventilation d'une année : pub_count + détail OA."""

    pub_year: int
    pub_count: int
    gold: int
    diamond: int
    hybrid: int
    bronze: int
    green: int
    embargoed: int
    closed: int
    unknown: int


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


class DocTypeFacet(BaseModel):
    value: str
    count: int


class StatsFacetsResponse(BaseModel):
    years: list[YearFacet]
    labs: list[LabFacet]
    oa_statuses: list[OaFacet]
    apc: list[ApcFacet]
    doc_types: list[DocTypeFacet]


class PivotDimensionOut(BaseModel):
    """Métadonnée d'une dimension, lue par les sélecteurs de l'interface : `groupable` pilote le
    choix de ventilation, `filterable` la barre de facettes (dérivée par soustraction)."""

    key: str
    label: str
    cardinality: Literal["low", "high"]
    ordinal: bool
    groupable: bool
    filterable: bool


class PivotMeasureOut(BaseModel):
    key: str
    label: str


class PivotSchemaResponse(BaseModel):
    """Vocabulaire du pivot exposé à l'interface (sans liaison SQL)."""

    dimensions: list[PivotDimensionOut]
    measures: list[PivotMeasureOut]


class PivotResponse(BaseModel):
    """Résultat d'une agrégation. Chaque ligne porte la valeur de chaque groupement (clés =
    `groups`) et la mesure sous la clé `value` (numérique, `null` si dénominateur nul)."""

    measure: str
    groups: list[str]
    rows: list[dict[str, str | int | float | None]]


class StatsQueries(Protocol):
    """Lectures pour /api/stats/*."""

    def pivot_schema(self) -> PivotSchemaResponse: ...

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
    ) -> PivotResponse: ...

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
    ) -> list[YearStatsRow]: ...

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
        doc_types: list[str],
    ) -> StatsFacetsResponse: ...
