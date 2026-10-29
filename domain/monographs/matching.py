"""Matching des monographies de même titre, selon l'éditeur et les ISBN.

Deux monographies de même titre sont compatibles si leurs éditeurs sont égaux ou l'un absent, et si au plus l'une a des ISBN. Deux ISBN différents désignent deux volumes d'un même ouvrage, ou deux éditions.
"""

from collections.abc import Sequence
from typing import NamedTuple


class MonographCandidate(NamedTuple):
    """Monographie de même titre qu'un enregistrement source."""

    id: int
    isbn: str | None
    eisbn: str | None
    publisher_id: int | None

    @property
    def has_isbn(self) -> bool:
        return bool(self.isbn or self.eisbn)


class MonographChoice(NamedTuple):
    """Monographie existante retenue, création d'une monographie, ou ni l'une ni l'autre."""

    monograph_id: int | None
    create: bool


_CREATE = MonographChoice(None, create=True)
_ABSTAIN = MonographChoice(None, create=False)


def _same_publisher(first: int | None, second: int | None) -> bool:
    return first is None or second is None or first == second


def choose_monograph(
    candidates: Sequence[MonographCandidate], *, publisher_id: int | None, has_isbn: bool
) -> MonographChoice:
    """Monographie d'un enregistrement source parmi celles de même titre, à défaut de monographie de même ISBN.

    Les monographies du même éditeur passent avant celles sans éditeur. Avec ISBN, l'enregistrement rejoint une monographie sans ISBN, sinon il en crée une. Sans ISBN, il rejoint la seule monographie compatible, ou la seule sans ISBN. Entre plusieurs volumes, il reste sans monographie. Sans monographie compatible, il en crée une.
    """
    compatible = [c for c in candidates if _same_publisher(c.publisher_id, publisher_id)]
    same = [c for c in compatible if publisher_id is not None and c.publisher_id == publisher_id]
    pool = same or compatible
    without_isbn = [c for c in pool if not c.has_isbn]
    if has_isbn:
        return MonographChoice(without_isbn[0].id, create=False) if without_isbn else _CREATE
    if len(pool) == 1:
        return MonographChoice(pool[0].id, create=False)
    if len(without_isbn) == 1:
        return MonographChoice(without_isbn[0].id, create=False)
    return _ABSTAIN if pool else _CREATE


def _compatible(first: MonographCandidate, second: MonographCandidate) -> bool:
    return _same_publisher(first.publisher_id, second.publisher_id) and not (
        first.has_isbn and second.has_isbn
    )


def _strength(candidate: MonographCandidate) -> tuple[bool, bool, int]:
    return (candidate.has_isbn, candidate.publisher_id is not None, -candidate.id)


def duplicate_monographs(
    same_title: Sequence[MonographCandidate],
) -> list[tuple[int, int]]:
    """Fusions `(cible, source)` parmi des monographies de même titre.

    Une monographie fusionne dans la seule monographie compatible, si celle-ci prime : par la présence d'ISBN, puis d'éditeur, puis par l'antériorité. Une monographie compatible avec plusieurs autres reste en place, faute de savoir laquelle elle double.
    """
    merges: list[tuple[int, int]] = []
    for source in same_title:
        partners = [c for c in same_title if c.id != source.id and _compatible(source, c)]
        if len(partners) == 1 and _strength(partners[0]) > _strength(source):
            merges.append((partners[0].id, source.id))
    return merges
