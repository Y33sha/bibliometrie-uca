"""Types de document des publications, leurs libellés et leurs familles."""

from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple


class DocType(StrEnum):
    """Type de document d'une publication. Reflet du type PostgreSQL `doc_type`."""

    ARTICLE = "article"
    CONFERENCE_PAPER = "conference_paper"
    CONFERENCE = "conference"
    RECORDED_TALK = "recorded_talk"
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


class DocTypeLabel(NamedTuple):
    """Libellés français d'un type de document."""

    singular: str
    plural: str


DOC_TYPE_LABELS: dict[DocType, DocTypeLabel] = {
    DocType.ARTICLE: DocTypeLabel("Article", "Articles"),
    DocType.CONFERENCE_PAPER: DocTypeLabel("Conference paper", "Conference papers"),
    DocType.CONFERENCE: DocTypeLabel("Communication", "Communications"),
    DocType.RECORDED_TALK: DocTypeLabel("Conférence filmée", "Conférences filmées"),
    DocType.BOOK: DocTypeLabel("Ouvrage", "Ouvrages"),
    DocType.BOOK_CHAPTER: DocTypeLabel("Chapitre", "Chapitres"),
    DocType.THESIS: DocTypeLabel("Thèse", "Thèses"),
    DocType.ONGOING_THESIS: DocTypeLabel("Thèse en cours", "Thèses en cours"),
    DocType.PREPRINT: DocTypeLabel("Preprint", "Preprints"),
    DocType.REVIEW: DocTypeLabel("Article de synthèse", "Articles de synthèse"),
    DocType.EDITORIAL: DocTypeLabel("Éditorial", "Éditoriaux"),
    DocType.REPORT: DocTypeLabel("Rapport", "Rapports"),
    DocType.PEER_REVIEW: DocTypeLabel("Peer review", "Peer reviews"),
    DocType.OTHER: DocTypeLabel("Autre", "Autres"),
    DocType.DATASET: DocTypeLabel("Données", "Données"),
    DocType.SOFTWARE: DocTypeLabel("Logiciel", "Logiciels"),
    DocType.PATENT: DocTypeLabel("Brevet", "Brevets"),
    DocType.HDR: DocTypeLabel("HDR", "HDR"),
    DocType.MEMOIR: DocTypeLabel("Mémoire", "Mémoires"),
    DocType.POSTER: DocTypeLabel("Poster", "Posters"),
    DocType.LETTER: DocTypeLabel("Lettre à l'éditeur", "Lettres à l'éditeur"),
    DocType.ERRATUM: DocTypeLabel("Erratum", "Errata"),
    DocType.RETRACTION: DocTypeLabel("Rétractation", "Rétractations"),
    DocType.BOOK_REVIEW: DocTypeLabel("Recension", "Recensions"),
    DocType.DATA_PAPER: DocTypeLabel("Data paper", "Data papers"),
    DocType.PROCEEDINGS: DocTypeLabel("Proceedings", "Proceedings"),
    DocType.MEDIA: DocTypeLabel("Intervention média", "Interventions média"),
    DocType.PHYSICAL_OBJECT: DocTypeLabel("Objet physique", "Objets physiques"),
}


@dataclass(frozen=True)
class DocTypeFamily:
    """Famille de types de document, qui groupe et filtre les listes."""

    label: str
    types: tuple[DocType, ...]


# Familles dans l'ordre d'affichage, leurs types aussi. Chaque type appartient à une seule famille.
DOC_TYPE_FAMILIES: dict[str, DocTypeFamily] = {
    "publications": DocTypeFamily(
        "Publications",
        (
            DocType.ARTICLE,
            DocType.CONFERENCE_PAPER,
            DocType.BOOK,
            DocType.BOOK_CHAPTER,
            DocType.REVIEW,
            DocType.DATA_PAPER,
        ),
    ),
    "preprints": DocTypeFamily("Prépublications", (DocType.PREPRINT,)),
    # Les mémoires sont exclus des listes et les thèses en cours y sont invisibles.
    "theses": DocTypeFamily(
        "Thèses", (DocType.THESIS, DocType.ONGOING_THESIS, DocType.HDR, DocType.MEMOIR)
    ),
    "data": DocTypeFamily(
        "Données & logiciels", (DocType.DATASET, DocType.SOFTWARE, DocType.PATENT)
    ),
    "misc": DocTypeFamily(
        "Annexes & divers",
        (
            DocType.OTHER,
            DocType.MEDIA,
            DocType.CONFERENCE,
            DocType.RECORDED_TALK,
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
    ),
}
