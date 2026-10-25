"""Éditeur d'un enregistrement source et d'une publication.

Une production hébergée sans être publiée n'a pas d'éditeur : la plateforme ou l'institution qui la diffuse n'en est pas l'éditeur.
"""

from collections.abc import Iterable

from domain.publications.doc_types import DocType
from domain.sources.registry import Source

UNPUBLISHED_DOC_TYPES: frozenset[str] = frozenset(
    {
        DocType.PREPRINT,
        DocType.DATASET,
        DocType.SOFTWARE,
        DocType.REPORT,
        DocType.THESIS,
        DocType.ONGOING_THESIS,
        DocType.HDR,
        DocType.MEMOIR,
        DocType.POSTER,
        DocType.CONFERENCE,
        DocType.PATENT,
    }
)
"""Types de documents sans éditeur."""


def is_published(doc_type: str | None) -> bool:
    """Vrai quand un document de ce type a un éditeur."""
    return doc_type not in UNPUBLISHED_DOC_TYPES


def source_record_has_publisher(doc_type: str | None, source: str, *, has_container: bool) -> bool:
    """Vrai quand l'éditeur que nomme la source est celui du document.

    Chez DataCite, un document sans série ni monographie est hébergé par un entrepôt, que la source nomme comme éditeur.
    """
    return is_published(doc_type) and (has_container or source != Source.DATACITE)


def publication_publisher(
    doc_type: str | None,
    prefix_publisher_id: int | None,
    record_publisher_ids: Iterable[int | None],
    *,
    platform_prefix: bool = False,
) -> int | None:
    """Éditeur d'une publication à la date de sa publication.

    C'est le titulaire du préfixe de son DOI Crossref, à défaut le premier éditeur de `record_publisher_ids`, rangés dans l'ordre de priorité des sources. Le titulaire d'un préfixe de plateforme d'éditeurs (`platform_prefix`) est la plateforme : il ne compte pas, ni un enregistrement source qui le nomme.
    """
    if not is_published(doc_type):
        return None
    if prefix_publisher_id is not None and not platform_prefix:
        return prefix_publisher_id
    excluded = prefix_publisher_id if platform_prefix else None
    return next((p for p in record_publisher_ids if p is not None and p != excluded), None)
