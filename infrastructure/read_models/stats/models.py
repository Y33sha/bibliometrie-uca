"""Modèles de réponse : agrégats des tableaux de bord."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from infrastructure.read_models._common import FacetOption


@dataclass(frozen=True, slots=True)
class StatsFilters:
    """Filtres des tableaux de bord, partagés par les facettes, les collaborations et le pivot.

    Les quatre lectures interrogent le même ensemble de publications : leurs décomptes ne se recouperaient pas si elles n'écoutaient pas les mêmes filtres. Une liste vide vaut absence de filtre. `has_apc` prend des valeurs de `yes` / `no` combinées en OR, comme dans la liste des publications.
    """

    lab_ids: list[int] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    publisher_ids: list[int] = field(default_factory=list)
    serial_ids: list[int] = field(default_factory=list)
    partner_rors: list[str] = field(default_factory=list)
    oa_status: list[str] = field(default_factory=list)
    license: list[str] = field(default_factory=list)
    has_apc: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)


class StatsFacetsResponse(BaseModel):
    years: list[FacetOption]
    labs: list[FacetOption]
    oa_statuses: list[FacetOption]
    licenses: list[FacetOption]
    apc: list[FacetOption]
    doc_types: list[FacetOption]


class PivotDimensionOut(BaseModel):
    """Métadonnée d'une dimension, lue par les sélecteurs de l'interface : `groupable` pilote le choix de ventilation, `comparable` celui de la comparaison (abscisse), `filterable` la barre de facettes (dérivée par soustraction)."""

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
    unit: str


class PivotSchemaResponse(BaseModel):
    """Vocabulaire du pivot exposé à l'interface (sans liaison SQL)."""

    dimensions: list[PivotDimensionOut]
    measures: list[PivotMeasureOut]


class PivotResponse(BaseModel):
    """Résultat d'une agrégation. Chaque ligne contient la valeur de chaque groupement (clés = `groups`) et la mesure sous la clé `value` (numérique, `null` si dénominateur nul)."""

    measure: str
    groups: list[str]
    rows: list[dict[str, str | int | float | None]]


class CountryCollaboration(BaseModel):
    """Décompte de collaborations pour un pays : code ISO 3166-1 alpha-2 (minuscule) et nombre de publications co-affiliées à ce pays."""

    code: str
    value: int


class CollaborationsResponse(BaseModel):
    """Collaborations internationales ventilées par pays étranger (source `publications.countries`).

    `international_count` = publications avec au moins un pays étranger ; `total_count` = corpus filtré. Leur rapport donne la part de publications en collaboration internationale."""

    rows: list[CountryCollaboration]
    international_count: int
    total_count: int
