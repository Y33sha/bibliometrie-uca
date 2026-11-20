"""Positions d'une contribution dans les listes d'auteurs de sa publication."""

from enum import StrEnum

from domain.sources.registry import Source


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


def is_truncated_list(source: str, length: int, longest: int) -> bool:
    """Vrai si la liste d'auteurs d'un enregistrement source est tronquée : plus courte que la plus longue liste de sa publication, et réduite à un auteur ou coupée par scanR (`SCANR_TRUNCATED_LENGTHS`). `propagate_contribution_attributes_sql` applique la même règle en SQL."""
    return length < longest and (
        length == 1 or (source == Source.SCANR and length in SCANR_TRUNCATED_LENGTHS)
    )
