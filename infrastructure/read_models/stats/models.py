"""Modèles de réponse : agrégats des tableaux de bord."""

from typing import Literal

from pydantic import BaseModel


class PivotDimensionOut(BaseModel):
    """Métadonnée d'une dimension, lue par les sélecteurs de l'interface."""

    key: str
    label: str
    cardinality: Literal["low", "high"]
    ordinal: bool
    comparable: bool
    """Vrai si la dimension sert d'axe de comparaison (abscisse)."""


class PivotIndicatorOut(BaseModel):
    """Indicateur du sélecteur de l'interface."""

    key: str
    label: str
    unit: str
    """Unité de la mesure, vide pour un nombre de publications."""
    breakdown: str
    """Dimension empilée dans chaque barre."""


class PivotSchemaResponse(BaseModel):
    """Vocabulaire du pivot exposé à l'interface (sans liaison SQL)."""

    dimensions: list[PivotDimensionOut]
    indicators: list[PivotIndicatorOut]


class PivotResponse(BaseModel):
    """Résultat d'une agrégation."""

    measure: str
    groups: list[str]
    rows: list[dict[str, str | int | float | None]]
    """Valeur de chaque groupement (clés de `groups`), et mesure sous la clé `value`, `null` si le dénominateur est nul."""


class CountryCollaboration(BaseModel):
    """Décompte de collaborations pour un pays."""

    code: str
    """Code ISO 3166-1 alpha-2, en minuscules."""
    value: int
    """Nombre de publications co-affiliées au pays."""


class CollaborationsResponse(BaseModel):
    """Collaborations internationales ventilées par pays étranger (source `publications.countries`)."""

    rows: list[CountryCollaboration]
    international_count: int
    """Nombre de publications avec au moins un pays étranger."""
    total_count: int
    """Nombre de publications du corpus filtré, dénominateur de la part des collaborations internationales."""
