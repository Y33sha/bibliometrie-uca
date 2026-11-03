"""Matching des monographies de même titre, selon l'éditeur et les ISBN.

Deux monographies de même titre sont compatibles si leurs éditeurs sont égaux ou l'un absent, et si au plus l'une a des ISBN. Deux ISBN différents désignent deux volumes d'un même ouvrage, ou deux éditions.
"""

from collections.abc import Sequence
from typing import NamedTuple


class MonographCandidate(NamedTuple):
    """Monographie d'un groupe de même titre."""

    id: int
    isbn: str | None
    eisbn: str | None
    publisher_id: int | None

    @property
    def has_isbn(self) -> bool:
        return bool(self.isbn or self.eisbn)


def compatible_publishers(first: int | None, second: int | None) -> bool:
    """Vrai si les deux éditeurs sont égaux ou l'un absent."""
    return first is None or second is None or first == second


def _compatible(first: MonographCandidate, second: MonographCandidate) -> bool:
    return compatible_publishers(first.publisher_id, second.publisher_id) and not (
        first.has_isbn and second.has_isbn
    )


def _strength(candidate: MonographCandidate) -> tuple[bool, bool, int]:
    return (candidate.has_isbn, candidate.publisher_id is not None, -candidate.id)


def duplicate_monographs(
    same_title: Sequence[MonographCandidate],
) -> list[tuple[int, int]]:
    """Renvoie les fusions `(cible, source)` parmi des monographies de même titre.

    Une monographie fusionne dans la seule monographie compatible, si celle-ci prime : par la présence d'ISBN, puis d'éditeur, puis par l'antériorité. Une monographie compatible avec plusieurs autres reste en place, faute de savoir laquelle elle double.
    """
    merges: list[tuple[int, int]] = []
    for source in same_title:
        partners = [c for c in same_title if c.id != source.id and _compatible(source, c)]
        if len(partners) == 1 and _strength(partners[0]) > _strength(source):
            merges.append((partners[0].id, source.id))
    return merges
