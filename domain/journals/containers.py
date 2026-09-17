"""Règles de rattachement d'un document à une revue et de typage d'une revue selon ses documents."""

from collections.abc import Iterable

from domain.journals.titles import names_a_dated_event, names_proceedings
from domain.source_publications.doc_types import map_doc_type

_BOOK_TYPES = frozenset({"book", "book_chapter"})
_CONFERENCE_PAPER = "conference_paper"


def _doc_types(raw_doc_type: str | None, source: str) -> set[str]:
    """Valeurs `doc_type` d'un type brut, composite ou non (WoS « Book Chapter; Proceedings Paper »)."""
    return {map_doc_type(part, source) for part in (raw_doc_type or "").split(";")}


def container_is_journal(
    raw_doc_type: str | None, source: str, *, has_issn: bool, declares_conference: bool = False
) -> bool:
    """Indique si le conteneur d'un document désigne une revue.

    Sans ISSN, le conteneur d'un livre ou d'un chapitre est le livre lui-même. Avec un ISSN, c'est sa collection. Un document issu d'un congrès garde son conteneur, le recueil d'actes : il déclare le congrès (`declares_conference`), ou son type composite mentionne un article de congrès.
    """
    if has_issn or declares_conference:
        return True
    types = _doc_types(raw_doc_type, source)
    return _CONFERENCE_PAPER in types or not types & _BOOK_TYPES


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
