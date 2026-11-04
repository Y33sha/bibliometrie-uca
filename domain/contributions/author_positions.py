"""Positions d'une contribution dans les listes d'auteurs de sa publication."""

from enum import StrEnum


class AuthorPosition(StrEnum):
    """Position d'une contribution, valeur de `contributions.author_positions`. Reflet du type PostgreSQL `author_position`."""

    CORRESPONDING = "corresponding"
    """Une contribution source de la contribution est correspondante."""
    FIRST = "first"
    """Contribution majoritaire au premier rang des listes d'auteurs."""
    LAST = "last"
    """Contribution majoritaire au dernier rang des listes d'auteurs complètes."""


SCANR_TRUNCATED_LENGTHS = (41, 51)
"""Longueurs auxquelles scanR coupe une liste d'auteurs."""
