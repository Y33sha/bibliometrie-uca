"""Groupes de signatures : les signatures d'un même auteur dans une publication, avec au maximum une signature par notice."""

from enum import StrEnum


class GroupingMethod(StrEnum):
    """Origine de l'appartenance d'une signature à son groupe. Mappe l'enum PostgreSQL `grouping_method`."""

    REFERENCE = "reference"
    """La signature fonde le groupe."""
    NAME = "name"
    """Patronyme, prénom ou initiale, uniques de part et d'autre."""
    IDENTIFIER = "identifier"
    """ORCID ou IdRef partagé, à patronyme égal."""
    ORDER = "order"
    """Rang parmi les signatures de même patronyme et de même initiale."""
    MODEL = "model"
    """Modèle probabiliste, avec un score et une marge."""
