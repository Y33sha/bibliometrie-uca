"""Port : lectures stats (consommé par le router stats).

Implémenté par `infrastructure.queries.api.stats.PgStatsQueries`. Co-localise les DTOs Pydantic retournés par ce port.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel

from application.ports.api.entity_facet import EntityFacetResponse


@dataclass(frozen=True)
class StatsFilters:
    """Filtres des tableaux de bord, partagés par les facettes, les collaborations et le pivot.

    Les quatre lectures interrogent le même ensemble de publications : leurs décomptes ne se recouperaient pas si elles n'écoutaient pas les mêmes filtres. Une liste vide vaut absence de filtre. `has_apc` porte une sélection de `uca` / `non_uca` / `none` combinée en OR.
    """

    lab_ids: list[int] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    publisher_ids: list[int] = field(default_factory=list)
    journal_ids: list[int] = field(default_factory=list)
    oa_status: list[str] = field(default_factory=list)
    has_apc: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)


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
    choix de ventilation, `comparable` celui de la comparaison (abscisse), `filterable` la barre de
    facettes (dérivée par soustraction)."""

    key: str
    label: str
    cardinality: Literal["low", "high"]
    ordinal: bool
    groupable: bool
    comparable: bool
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


class CountryCollaboration(BaseModel):
    """Décompte de collaborations pour un pays : code ISO 3166-1 alpha-2 (minuscule) et nombre de
    publications co-affiliées à ce pays."""

    code: str
    value: int


class CollaborationsResponse(BaseModel):
    """Collaborations internationales ventilées par pays étranger (source `publications.countries`).

    `international_count` = publications avec au moins un pays étranger ; `total_count` = corpus filtré.
    Leur rapport donne la part de publications en collaboration internationale."""

    rows: list[CountryCollaboration]
    international_count: int
    total_count: int


class StatsQueries(Protocol):
    """Lectures pour /api/stats/*."""

    def pivot_schema(self) -> PivotSchemaResponse: ...

    def pivot(self, *, measure: str, groups: list[str], filters: StatsFilters) -> PivotResponse: ...

    def collaborations(self, *, filters: StatsFilters) -> CollaborationsResponse: ...

    def stats_entity_facet(
        self,
        *,
        kind: Literal["publisher", "journal"],
        search: str,
        filters: StatsFilters,
    ) -> EntityFacetResponse: ...

    def stats_facets(self, *, filters: StatsFilters) -> StatsFacetsResponse: ...
