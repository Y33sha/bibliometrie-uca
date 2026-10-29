"""Types de document des publications, et leurs familles."""

from enum import StrEnum


class DocType(StrEnum):
    """Type de document d'une publication. Reflet du type PostgreSQL `doc_type`."""

    ARTICLE = "article"
    CONFERENCE_PAPER = "conference_paper"
    CONFERENCE = "conference"
    BOOK = "book"
    BOOK_CHAPTER = "book_chapter"
    THESIS = "thesis"
    ONGOING_THESIS = "ongoing_thesis"
    PREPRINT = "preprint"
    REVIEW = "review"
    EDITORIAL = "editorial"
    REPORT = "report"
    PEER_REVIEW = "peer_review"
    OTHER = "other"
    DATASET = "dataset"
    SOFTWARE = "software"
    PATENT = "patent"
    HDR = "hdr"
    MEMOIR = "memoir"
    POSTER = "poster"
    LETTER = "letter"
    ERRATUM = "erratum"
    RETRACTION = "retraction"
    BOOK_REVIEW = "book_review"
    DATA_PAPER = "data_paper"
    PROCEEDINGS = "proceedings"
    MEDIA = "media"
    PHYSICAL_OBJECT = "physical_object"


DOC_TYPES: tuple[DocType, ...] = tuple(DocType)
DOC_TYPES_SET: frozenset[str] = frozenset(DocType)

# Sous-types d'article, qui l'emportent sur `article` à l'agrégation (`arbitrate_doc_type_with_article_subtype`).
ARTICLE_SUBTYPES: frozenset[str] = frozenset(
    {
        DocType.REVIEW,
        DocType.BOOK_REVIEW,
        DocType.DATA_PAPER,
        DocType.CONFERENCE_PAPER,
        DocType.CONFERENCE,
        DocType.EDITORIAL,
        DocType.LETTER,
        DocType.ERRATUM,
        DocType.RETRACTION,
    }
)

# Familles de types de document, dans l'ordre d'affichage. Chaque type appartient à une famille.
DOC_TYPE_FAMILIES: dict[str, tuple[DocType, ...]] = {
    "publications": (
        DocType.ARTICLE,
        DocType.CONFERENCE_PAPER,
        DocType.BOOK,
        DocType.BOOK_CHAPTER,
        DocType.REVIEW,
        DocType.DATA_PAPER,
    ),
    "preprints": (DocType.PREPRINT,),
    "theses": (DocType.THESIS, DocType.ONGOING_THESIS, DocType.HDR, DocType.MEMOIR),
    "data": (DocType.DATASET, DocType.SOFTWARE, DocType.PATENT),
    "misc": (
        DocType.OTHER,
        DocType.MEDIA,
        DocType.POSTER,
        DocType.REPORT,
        DocType.ERRATUM,
        DocType.RETRACTION,
        DocType.PEER_REVIEW,
        DocType.EDITORIAL,
        DocType.LETTER,
        DocType.BOOK_REVIEW,
        DocType.PROCEEDINGS,
        DocType.PHYSICAL_OBJECT,
    ),
}
