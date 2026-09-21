"""Règles de rattachement d'un document à son conteneur, revue ou monographie, et de typage d'une revue selon ses documents."""

from collections.abc import Iterable
from enum import StrEnum

from domain.journals.titles import names_a_dated_event, names_proceedings
from domain.source_publications.doc_types import map_doc_type

_BOOK = "book"
_BOOK_CHAPTER = "book_chapter"
_CONFERENCE_PAPER = "conference_paper"


class ContainerRole(StrEnum):
    """Ce que le conteneur d'un document désigne."""

    JOURNAL = "journal"
    """Le document paraît dans une revue."""
    BOOK = "book"
    """Le document est lui-même un livre : sa monographie porte son titre."""
    PART = "part"
    """Le document est un chapitre ou un article de congrès : sa monographie est le livre ou le volume d'actes qui le contient."""


def _doc_types(raw_doc_type: str | None, source: str) -> set[str]:
    """Valeurs `doc_type` d'un type brut, composite ou non (WoS « Book Chapter; Proceedings Paper »)."""
    return {map_doc_type(part, source) for part in (raw_doc_type or "").split(";")}


def container_role(
    raw_doc_type: str | None, source: str, *, declares_conference: bool = False
) -> ContainerRole:
    """Rôle du conteneur d'un document, d'après son type brut dans la source. Un document qui déclare un congrès (`declares_conference`) est un article de congrès."""
    types = _doc_types(raw_doc_type, source)
    if declares_conference or types & {_BOOK_CHAPTER, _CONFERENCE_PAPER}:
        return ContainerRole.PART
    if _BOOK in types:
        return ContainerRole.BOOK
    return ContainerRole.JOURNAL


def is_conference(
    raw_doc_type: str | None, source: str, *, declares_conference: bool = False
) -> bool:
    """Indique si un document est issu d'un congrès : sa monographie est un volume d'actes."""
    return declares_conference or _CONFERENCE_PAPER in _doc_types(raw_doc_type, source)


def conference_paper_share(records: Iterable[tuple[str, str | None]]) -> tuple[int, int]:
    """Nombre d'articles de congrès et nombre de documents d'une revue.

    `records` : `(source, type brut)` de chaque document. Le type brut évite de compter les documents que la correction a retypés d'après le type de la revue.
    """
    total = conference = 0
    for source, raw_doc_type in records:
        total += 1
        conference += _CONFERENCE_PAPER in _doc_types(raw_doc_type, source)
    return conference, total


def is_dated_event_without_issn(title: str, *, has_issn: bool) -> bool:
    """Indique si une revue sans ISSN porte le titre d'une édition datée de congrès (`names_a_dated_event`). Une revue avec ISSN peut porter une année dans son titre (« Periodontology 2000 »)."""
    return not has_issn and names_a_dated_event(title)


def is_proceedings_title_without_issn(title: str, *, has_issn: bool) -> bool:
    """Indique si une revue sans ISSN porte un titre d'actes (`names_proceedings`)."""
    return not has_issn and names_proceedings(title)


def holds_mostly_conference_papers(records: Iterable[tuple[str, str | None]]) -> bool:
    """Indique si la majorité stricte des documents d'une revue sont des articles de congrès (`conference_paper_share`)."""
    conference, total = conference_paper_share(records)
    return conference * 2 > total
