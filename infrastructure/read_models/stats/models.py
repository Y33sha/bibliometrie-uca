"""Modèles de réponse : agrégats des tableaux de bord."""

from typing import Literal

from pydantic import BaseModel

from infrastructure.read_models._common import FacetOption


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


class PivotIndicatorOut(BaseModel):
    """Indicateur du sélecteur de l'interface. `unit` est l'unité de sa mesure, vide pour un nombre de publications. `breakdown` est la dimension empilée dans chaque barre."""

    key: str
    label: str
    unit: str
    breakdown: str


class PivotSchemaResponse(BaseModel):
    """Vocabulaire du pivot exposé à l'interface (sans liaison SQL)."""

    dimensions: list[PivotDimensionOut]
    indicators: list[PivotIndicatorOut]


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
