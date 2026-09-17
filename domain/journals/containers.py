"""Règle de rattachement d'un document à une revue selon son type."""

from domain.source_publications.doc_types import map_doc_type

_BOOK_TYPES = frozenset({"book", "book_chapter"})


def container_is_journal(raw_doc_type: str | None, source: str, *, has_issn: bool) -> bool:
    """Indique si le conteneur d'un document désigne une revue.

    Sans ISSN, le conteneur d'un livre ou d'un chapitre est le livre lui-même. Avec un ISSN, c'est sa collection. Un type composite (WoS « Book Chapter; Proceedings Paper ») qui mentionne un article de congrès garde son conteneur, le recueil d'actes.
    """
    if has_issn:
        return True
    types = {map_doc_type(part, source) for part in (raw_doc_type or "").split(";")}
    return "conference_paper" in types or not types & _BOOK_TYPES
