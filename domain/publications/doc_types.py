"""Taxonomie canonique des `doc_type` : enum, ensembles et familles.

Vocabulaire partagé de la couche canonique — la valeur de l'enum PostgreSQL `doc_type` de la table `publications`, ses sous-types d'article prioritaires à l'arbitrage, et le regroupement en familles pour la ventilation. Le mapping des nomenclatures sources vers cette taxonomie vit côté source (`domain/source_publications/doc_types.py`).
"""

from enum import StrEnum


class DocType(StrEnum):
    """Type de document canonique — les membres portent les libellés de l'enum PostgreSQL `doc_type`."""

    ARTICLE = "article"
    CONFERENCE_PAPER = "conference_paper"
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


DOC_TYPES: tuple[DocType, ...] = tuple(DocType)
DOC_TYPES_SET: frozenset[str] = frozenset(DocType)

# Sous-types qui priment sur "article" générique : si une source prioritaire
# (typiquement CrossRef avec "journal-article") dit "article", mais qu'une
# source moins prioritaire (HAL, OA…) reconnaît un sous-type plus précis,
# on préfère le sous-type pour ne pas perdre l'information.
#
# CrossRef ne distingue pas ces sous-types (tout est "journal-article") ;
# HAL fait la distinction via ses combinaisons type_sous-type
# ("art_artrev" → "review", "art_bookreview" → "book_review", etc.).
# L'arbitrage vit dans `domain/publications/aggregation.py`
# (`arbitrate_doc_type_with_article_subtype`).
ARTICLE_SUBTYPES: frozenset[str] = frozenset(
    {
        DocType.REVIEW,
        DocType.BOOK_REVIEW,
        DocType.DATA_PAPER,
        DocType.CONFERENCE_PAPER,
        DocType.EDITORIAL,
        DocType.LETTER,
        DocType.ERRATUM,
        DocType.RETRACTION,
    }
)

# Famille → types fins. Mémoires/thèses en cours filtrés ailleurs, mais classés ici pour
# l'exhaustivité de la couverture de l'enum. L'ordre est celui d'affichage.
DOC_TYPE_FAMILIES: dict[str, tuple[str, ...]] = {
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
    ),
}
