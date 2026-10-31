"""Correction des métadonnées par table de règles, pour un enregistrement source comme pour une publication.

`effective_metadata` applique les règles aux faits de `MetadataForCorrection`. Elle corrige `doc_type`.

Une règle est un membre de `MetadataCorrectionRule` et son entrée dans `_RULES`. `applies_to` liste ses prédicats, tous requis. `applies_correction` donne la valeur cible de chaque champ corrigé. Pour un champ, la première règle de `_RULES` qui s'applique l'emporte.

Les prédicats sont les clés de `_AppliesTo`. Une clé qui nomme un champ de `MetadataForCorrection` teste l'égalité. Les autres clés ont leur branche dans `_check_predicate`.

Un fait inconnu vaut `None`, et les prédicats qui le testent sont faux. Une publication connaît seulement les faits de `MetadataForCorrection.for_publication`.
"""

import re
from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import NamedTuple, TypedDict

from domain.normalize import normalize_text
from domain.platforms.registry import preprint_servers_of_doi
from domain.publications.doc_types import DocType
from domain.publishers.publisher import PublisherType
from domain.serials.serial import SerialType
from domain.source_records.identifiers import SourceIdentifier, SourceIdentifierType


@dataclass(frozen=True, slots=True)
class MetadataForCorrection:
    """Faits lus par les règles de correction, pour un enregistrement source ou une publication."""

    title: str
    doc_type: str | None
    serial_id: int | None
    dois: frozenset[str] = frozenset()
    """DOI propres actifs d'un enregistrement source (`own_dois`), DOI d'une publication."""
    serial_type: str | None = None
    urls: list[str] | None = None
    self_declared_preprint: bool | None = None
    """L'enregistrement source déclare la relation Crossref `is-preprint-of` : il est le preprint d'une autre œuvre."""
    declares_conference: bool | None = None
    """L'enregistrement source nomme le congrès dont il est issu (Crossref `event`, ou `assertion` Springer)."""
    registrant_publisher_types: frozenset[str] = frozenset()
    """Types des éditeurs qui ont déposé le préfixe de l'un des `dois` (`doi_prefixes`)."""
    in_proceedings_volume: bool | None = None
    """La monographie de l'enregistrement source est un volume d'actes (`monographs.proceedings`)."""
    group_title: str | None = None
    """Forme de présentation d'un `posted-content` Crossref (`oral`, `pico`, `display`)."""
    source: str | None = None
    author_count: int | None = None
    """`source_records.author_count` : contributions sources d'auteur non collectives."""
    preprint_server_dois: bool = field(init=False)
    """Les `dois`, un au moins, sont tous des DOI de serveur de preprints (`preprint_servers_of_doi`)."""

    def __post_init__(self) -> None:
        on_server = bool(self.dois) and all(preprint_servers_of_doi(doi) for doi in self.dois)
        object.__setattr__(self, "preprint_server_dois", on_server)

    @classmethod
    def for_publication(
        cls,
        *,
        title: str,
        doc_type: str | None,
        doi: str | None,
        serial_id: int | None,
        serial_type: str | None,
    ) -> MetadataForCorrection:
        """Construit les faits d'une publication : les champs arbitrés par l'agrégation, et le type de sa revue."""
        return cls(
            title=title,
            doc_type=doc_type,
            dois=frozenset({doi} if doi else ()),
            serial_id=serial_id,
            serial_type=serial_type,
        )


class MetadataCorrectionRule(StrEnum):
    """Règle de correction, nommée `ENTRÉE_CONDITION_TO_SORTIE`. Sa valeur s'enregistre dans `corrections.<champ>.corrected_by`, de `source_records` comme de `publications`."""

    THESES_FR_URL_TO_THESIS = "THESES_FR_URL_TO_THESIS"
    DUMAS_URL_TO_MEMOIR = "DUMAS_URL_TO_MEMOIR"
    THESIS_WITH_SERIAL_TO_ARTICLE = "THESIS_WITH_SERIAL_TO_ARTICLE"
    SERIAL_TYPE_MEDIA_TO_MEDIA = "SERIAL_TYPE_MEDIA_TO_MEDIA"
    SERIAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER = "SERIAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER"
    CONFERENCE_DECLARED_TO_CONFERENCE_PAPER = "CONFERENCE_DECLARED_TO_CONFERENCE_PAPER"
    PROCEEDINGS_VOLUME_TO_CONFERENCE_PAPER = "PROCEEDINGS_VOLUME_TO_CONFERENCE_PAPER"
    PRESENTATION_ORAL_TO_CONFERENCE = "PRESENTATION_ORAL_TO_CONFERENCE"
    PRESENTATION_DISPLAY_TO_POSTER = "PRESENTATION_DISPLAY_TO_POSTER"
    DOI_REGISTRANT_MEDIA_TO_MEDIA = "DOI_REGISTRANT_MEDIA_TO_MEDIA"
    CROSSREF_AUTHORLESS_VOLUME_TITLE_TO_PROCEEDINGS = (
        "CROSSREF_AUTHORLESS_VOLUME_TITLE_TO_PROCEEDINGS"
    )
    CROSSREF_VOLUME_TITLE_PREFIX_TO_PROCEEDINGS = "CROSSREF_VOLUME_TITLE_PREFIX_TO_PROCEEDINGS"
    DOI_PREPRINT_SERVER_TO_PREPRINT = "DOI_PREPRINT_SERVER_TO_PREPRINT"
    PREPRINT_RELATION_TO_PREPRINT = "PREPRINT_RELATION_TO_PREPRINT"
    TITLE_MEDIA_PREFIX_TO_MEDIA = "TITLE_MEDIA_PREFIX_TO_MEDIA"
    TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET = "TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET"
    TITLE_ERRATUM_PREFIX_TO_ERRATUM = "TITLE_ERRATUM_PREFIX_TO_ERRATUM"
    TITLE_RETRACTION_PREFIX_TO_RETRACTION = "TITLE_RETRACTION_PREFIX_TO_RETRACTION"
    TITLE_EDITORIAL_PREFIX_TO_EDITORIAL = "TITLE_EDITORIAL_PREFIX_TO_EDITORIAL"
    TITLE_LETTER_PREFIX_TO_LETTER = "TITLE_LETTER_PREFIX_TO_LETTER"
    TITLE_SYSTEMATIC_REVIEW_TO_REVIEW = "TITLE_SYSTEMATIC_REVIEW_TO_REVIEW"
    TITLE_ISBN_TO_BOOK_REVIEW = "TITLE_ISBN_TO_BOOK_REVIEW"
    TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW = "TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW"
    TITLE_RECENSION_TO_BOOK_REVIEW = "TITLE_RECENSION_TO_BOOK_REVIEW"
    SERIAL_TYPE_DATA_JOURNAL_TO_DATA_PAPER = "SERIAL_TYPE_DATA_JOURNAL_TO_DATA_PAPER"
    DOI_FIGSHARE_COLLECTION_TO_DATASET = "DOI_FIGSHARE_COLLECTION_TO_DATASET"
    SCANR_FROM_HAL_TO_HAL_TYPE = "SCANR_FROM_HAL_TO_HAL_TYPE"
    HAL_DEPOSIT_MISSING_TO_REMOVED = "HAL_DEPOSIT_MISSING_TO_REMOVED"


class Correction[T](NamedTuple):
    """Valeur corrigée, et règle qui la produit."""

    value: T
    rule: MetadataCorrectionRule


class CorrectedFields(NamedTuple):
    """Correction de chaque champ, `None` sans correction."""

    doc_type: Correction[str] | None = None


# Débuts de titre normalisé d'une intervention dans les médias.
_MEDIA_TITLE_PREFIXES = ("interview", "reportage", "podcast")

# Débuts de titre normalisé d'un contenu supplémentaire. « Supplementary roles of X » est un article.
_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES = (
    "additional file",
    "supplementary material",
    "supplementary data",
    "supplementary information",
    "supplementary file",  # couvre "file" et "files"
    "supplementary dataset",  # couvre "dataset" et "datasets"
    "supplementary video",
    "supplementary movie",
    "supporting video",
    "supporting movie",
    "data from",
)

# Débuts de titre normalisé d'un erratum.
_ERRATUM_TITLE_PREFIXES = (
    DocType.ERRATUM,
    "errata",
    "corrigendum",
    "author correction",
    "publisher correction",
)

# Débuts de titre normalisé d'un avis de rétractation. « Retraction of consent in clinical trials » est un article.
_RETRACTION_TITLE_PREFIXES = ("retraction notice", "retraction note")

# « Editorial: <titre> » (Frontiers). Le deux-points écarte « Editorial Board » ; `normalize_text` l'efface, d'où un motif sur le titre brut.
_EDITORIAL_PREFIX_PATTERN = re.compile(r"^\s*editorial\s*:", re.IGNORECASE)
# « Letter: <titre> » (courrier à l'éditeur, research letter).
_LETTER_PREFIX_PATTERN = re.compile(r"^\s*letter\s*:", re.IGNORECASE)
# « Systematic review » en tête de titre ou de sous-titre. Au fil du titre (« …cohort, and a systematic review »), la mention désigne une étude primaire.
_SYSTEMATIC_REVIEW_PATTERN = re.compile(r"(^|:\s*)(a\s+)?systematic reviews?\b", re.IGNORECASE)

# Recension d'ouvrage : mention « ISBN », ou ISBN-13, dans le titre brut.
_ISBN_PATTERN = re.compile(r"\bisbn\b|\b97[89][-\s0-9]{10,17}\b", re.IGNORECASE)
# Recension d'ouvrage : titre terminé par « AAAA, N p. », référence de l'ouvrage saisie dans le titre (HAL). Moins sûr que l'ISBN.
_YEAR_PAGES_END_PATTERN = re.compile(
    r"(19|20)\d{2}[\s,.]+\d{1,4}\s*(pp|pages?|p)\.?\s*$", re.IGNORECASE
)
# Recension d'ouvrage : titre commençant par « Recension » ou « Compte(s) rendu(s) : ». Le deux-points écarte les rapports (« Compte rendu de mission : … »).
_RECENSION_TITLE_PATTERN = re.compile(r"^\s*(recension|comptes?\s+rendus?\s*:)", re.IGNORECASE)

# Vocabulaire d'un volume d'actes ou d'un recueil de résumés, n'importe où dans le titre. Seul, il désigne aussi des articles (discours présidentiel, introduction éditoriale) : la règle qui le lit exige un enregistrement source sans auteur.
_VOLUME_TITLE_PATTERN = re.compile(
    r"\b(proceedings|abstracts?|congress|congrès|congres|meeting|symposium|conference|colloque"
    r"|communications\s+affich[ée]es|poster\s+presentations|posters)\b",
    re.IGNORECASE,
)
# Début de titre d'un volume. « Abstract » au singulier en est exclu : « Abstract 4007: … » est un résumé isolé.
_VOLUME_TITLE_PREFIX_PATTERN = re.compile(
    r"^\s*(proceedings|abstracts|book\s+of\s+abstracts|abstract\s+book)\b", re.IGNORECASE
)

# Préfixes DOI des registres de thèses, dont le DOI est celui de la thèse elle-même : `10.70675` (ABES).
# Les thèses des archives institutionnelles ont des préfixes variés, absents de la liste.
_THESIS_REGISTRY_DOI_PREFIXES = ("10.70675",)


class _AppliesTo(TypedDict, total=False):
    """Prédicats d'une règle, tous requis.

    Une clé au nom d'un champ de `MetadataForCorrection` est une égalité sur ce champ.
    """

    doc_type: str | frozenset[str]
    """Type ou types de document, comparés en minuscules. Limite la règle aux types plausibles."""
    doc_type_not_in: frozenset[str]
    """Types laissés en l'état par la règle. Un type absent est hors de l'ensemble."""
    serial_type: str
    url_contains: str
    """Sous-chaîne d'au moins une des `urls`."""
    doi_contains: str
    """Sous-chaîne d'au moins un des `dois`."""
    title_prefix_normalized: tuple[str, ...]
    """Préfixes de `normalize_text(title)`."""
    title_regex: re.Pattern[str]
    """Motif cherché dans le titre."""
    serial_id_present: bool
    """Présence d'un `serial_id`."""
    doi_prefix_not_in: tuple[str, ...]
    """Au moins un des `dois` a un préfixe hors du tuple."""
    preprint_server_dois: bool
    self_declared_preprint: bool
    declares_conference: bool
    registrant_publisher_type: str
    """Élément de `registrant_publisher_types`."""
    in_proceedings_volume: bool
    group_title: frozenset[str]
    """Valeurs admises, comparées en minuscules."""
    source: str
    author_count_max: int
    """`author_count` connu et au plus égal à la valeur."""


class _AppliesCorrection(TypedDict, total=False):
    """Champ corrigé et sa valeur cible."""

    doc_type: str


class _RuleDefinition(TypedDict):
    applies_to: _AppliesTo
    applies_correction: _AppliesCorrection


# Types qu'une règle de titre peut corriger.
_ARTICLE_OR_OTHER = frozenset({DocType.ARTICLE, DocType.OTHER})


# Ordre de priorité : URL, type de revue, puis titre.
_RULES: dict[MetadataCorrectionRule, _RuleDefinition] = {
    # theses.fr fait autorité sur les thèses françaises. Un enregistrement source theses.fr rattaché à une revue relève de `THESIS_WITH_SERIAL_TO_ARTICLE`.
    MetadataCorrectionRule.THESES_FR_URL_TO_THESIS: {
        "applies_to": {"url_contains": "theses.fr/", "serial_id_present": False},
        "applies_correction": {"doc_type": DocType.THESIS},
    },
    # DUMAS héberge des mémoires et des thèses d'exercice. Seul l'enregistrement source HAL distingue la thèse d'exercice, par le diplôme : elle garde son type. Même exception que theses.fr pour un enregistrement source rattaché à une revue.
    MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR: {
        "applies_to": {
            "url_contains": "dumas.ccsd",
            "serial_id_present": False,
            "doc_type_not_in": frozenset({DocType.PRACTICE_THESIS}),
        },
        "applies_correction": {"doc_type": DocType.MEMOIR},
    },
    # Thèse ou mémoire rattaché à une revue, avec un DOI d'éditeur : c'est l'article publié, que OpenAlex ou ScanR confondent avec la thèse.
    # Avec un DOI de registre de thèses, ou sans DOI, le type reste thèse. L'article perd ses identifiants de thèse (`is_dissertation_identifier`).
    MetadataCorrectionRule.THESIS_WITH_SERIAL_TO_ARTICLE: {
        "applies_to": {
            "doc_type": frozenset(
                {DocType.THESIS, DocType.ONGOING_THESIS, DocType.PRACTICE_THESIS, DocType.MEMOIR}
            ),
            "serial_id_present": True,
            "doi_prefix_not_in": _THESIS_REGISTRY_DOI_PREFIXES,
        },
        "applies_correction": {"doc_type": DocType.ARTICLE},
    },
    # Revue typée `media` à la main ⇒ `media`, quel que soit le `doc_type`.
    MetadataCorrectionRule.SERIAL_TYPE_MEDIA_TO_MEDIA: {
        "applies_to": {"serial_type": SerialType.MEDIA},
        "applies_correction": {"doc_type": DocType.MEDIA},
    },
    # DOI déposé par un éditeur de presse ⇒ `media`, quel que soit le `doc_type`. The Conversation dépose ses articles sans titre de revue.
    MetadataCorrectionRule.DOI_REGISTRANT_MEDIA_TO_MEDIA: {
        "applies_to": {"registrant_publisher_type": PublisherType.MEDIA},
        "applies_correction": {"doc_type": DocType.MEDIA},
    },
    # Enregistrement source Crossref sans auteur dont le titre nomme un volume d'actes ou un recueil de résumés ⇒ `proceedings`.
    MetadataCorrectionRule.CROSSREF_AUTHORLESS_VOLUME_TITLE_TO_PROCEEDINGS: {
        "applies_to": {
            "source": "crossref",
            "author_count_max": 0,
            "doc_type": frozenset({DocType.ARTICLE, DocType.CONFERENCE_PAPER, DocType.OTHER}),
            "title_regex": _VOLUME_TITLE_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.PROCEEDINGS},
    },
    # Enregistrement source Crossref dont le titre commence par un mot de volume ⇒ `proceedings`, quel que soit son nombre d'auteurs.
    MetadataCorrectionRule.CROSSREF_VOLUME_TITLE_PREFIX_TO_PROCEEDINGS: {
        "applies_to": {
            "source": "crossref",
            "doc_type": frozenset({DocType.ARTICLE, DocType.CONFERENCE_PAPER, DocType.OTHER}),
            "title_regex": _VOLUME_TITLE_PREFIX_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.PROCEEDINGS},
    },
    # Article ou chapitre d'une revue d'actes ⇒ `conference_paper`. Un `book` peut être un volume entier d'actes.
    MetadataCorrectionRule.SERIAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER: {
        "applies_to": {
            "serial_type": SerialType.PROCEEDINGS,
            "doc_type": frozenset({DocType.ARTICLE, DocType.BOOK_CHAPTER}),
        },
        "applies_correction": {"doc_type": DocType.CONFERENCE_PAPER},
    },
    # Article ou chapitre d'un volume d'actes (sa monographie) ⇒ `conference_paper`.
    MetadataCorrectionRule.PROCEEDINGS_VOLUME_TO_CONFERENCE_PAPER: {
        "applies_to": {
            "in_proceedings_volume": True,
            "doc_type": frozenset({DocType.ARTICLE, DocType.BOOK_CHAPTER}),
        },
        "applies_correction": {"doc_type": DocType.CONFERENCE_PAPER},
    },
    # Contenu déposé sans sous-type `preprint`, présenté oralement (`oral`, `pico`) ⇒ `conference`. Copernicus dépose ainsi les résumés de ses réunions (assemblée générale de l'EGU).
    MetadataCorrectionRule.PRESENTATION_ORAL_TO_CONFERENCE: {
        "applies_to": {"doc_type": DocType.OTHER, "group_title": frozenset({"oral", "pico"})},
        "applies_correction": {"doc_type": DocType.CONFERENCE},
    },
    # Même contenu présenté en session d'affichage (`display`) ⇒ `poster`.
    MetadataCorrectionRule.PRESENTATION_DISPLAY_TO_POSTER: {
        "applies_to": {"doc_type": DocType.OTHER, "group_title": frozenset({"display"})},
        "applies_correction": {"doc_type": DocType.POSTER},
    },
    # Chapitre qui nomme le congrès dont il est issu ⇒ `conference_paper`. Springer décrit ainsi les actes publiés en livre.
    MetadataCorrectionRule.CONFERENCE_DECLARED_TO_CONFERENCE_PAPER: {
        "applies_to": {
            "declares_conference": True,
            "doc_type": DocType.BOOK_CHAPTER,
        },
        "applies_correction": {"doc_type": DocType.CONFERENCE_PAPER},
    },
    # DOI de serveur de preprints (arXiv, bioRxiv, SSRN, Research Square, …), sans revue + doc_type ∈ {article, other} ⇒ `preprint`. Une revue désigne l'article publié, déposé sous le DOI du preprint.
    MetadataCorrectionRule.DOI_PREPRINT_SERVER_TO_PREPRINT: {
        "applies_to": {
            "preprint_server_dois": True,
            "serial_id_present": False,
            "doc_type": _ARTICLE_OR_OTHER,
        },
        "applies_correction": {"doc_type": DocType.PREPRINT},
    },
    # L'enregistrement source se déclare preprint d'une autre œuvre (relation Crossref `is-preprint-of`). La déclaration prime sur tout type de document, absent compris.
    MetadataCorrectionRule.PREPRINT_RELATION_TO_PREPRINT: {
        "applies_to": {"self_declared_preprint": True},
        "applies_correction": {"doc_type": DocType.PREPRINT},
    },
    # Titre `interview`/`reportage`/`podcast` + `doc_type` ∈ {article, other, recorded_talk} ⇒ `media`.
    MetadataCorrectionRule.TITLE_MEDIA_PREFIX_TO_MEDIA: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER | {DocType.RECORDED_TALK},
            "title_prefix_normalized": _MEDIA_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": DocType.MEDIA},
    },
    # Collection Figshare (`10.6084/m9.figshare.c.<id>`), ensemble de fichiers supplémentaires ⇒ `dataset`. Son titre est celui de l'article, d'où une règle sur le DOI.
    MetadataCorrectionRule.DOI_FIGSHARE_COLLECTION_TO_DATASET: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "doi_contains": "m9.figshare.c.",
        },
        "applies_correction": {"doc_type": DocType.DATASET},
    },
    # Titre de fichiers complémentaires + doc_type ∈ {article, other, conference, recorded_talk} ⇒ `dataset`. DataCite et des entrepôts (Dryad, Zenodo) les décrivent à part ; Figshare en type certains `Presentation`, DataCite les vidéos `Audiovisual`.
    MetadataCorrectionRule.TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER | {DocType.CONFERENCE, DocType.RECORDED_TALK},
            "title_prefix_normalized": _SUPPLEMENTARY_CONTENT_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": DocType.DATASET},
    },
    # Titre d'erratum ⇒ `erratum`. OpenAlex type souvent les errata `article`, `preprint` ou `data_paper`.
    MetadataCorrectionRule.TITLE_ERRATUM_PREFIX_TO_ERRATUM: {
        "applies_to": {
            "doc_type": frozenset(
                {
                    DocType.ARTICLE,
                    DocType.PREPRINT,
                    DocType.REVIEW,
                    DocType.CONFERENCE_PAPER,
                    DocType.DATA_PAPER,
                    DocType.LETTER,
                    DocType.OTHER,
                }
            ),
            "title_prefix_normalized": _ERRATUM_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": DocType.ERRATUM},
    },
    # Titre d'avis de rétractation + doc_type ∈ {article, other} ⇒ `retraction`.
    MetadataCorrectionRule.TITLE_RETRACTION_PREFIX_TO_RETRACTION: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "title_prefix_normalized": _RETRACTION_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": DocType.RETRACTION},
    },
    # Titre « Editorial: … » + doc_type ∈ {article, other} ⇒ `editorial`. Les sources typent souvent ces éditoriaux `article`.
    MetadataCorrectionRule.TITLE_EDITORIAL_PREFIX_TO_EDITORIAL: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "title_regex": _EDITORIAL_PREFIX_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.EDITORIAL},
    },
    # Titre « Letter: … » + doc_type ∈ {article, other} ⇒ `letter`.
    MetadataCorrectionRule.TITLE_LETTER_PREFIX_TO_LETTER: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "title_regex": _LETTER_PREFIX_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.LETTER},
    },
    # Titre de revue systématique + doc_type `article` ⇒ `review`. Une revue systématique peut aussi être un poster, un preprint ou un mémoire.
    MetadataCorrectionRule.TITLE_SYSTEMATIC_REVIEW_TO_REVIEW: {
        "applies_to": {
            "doc_type": frozenset({DocType.ARTICLE}),
            "title_regex": _SYSTEMATIC_REVIEW_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.REVIEW},
    },
    # Titre avec un ISBN + doc_type ∈ {article, review, other} ⇒ `book_review`. Un livre ou un chapitre a parfois son propre ISBN dans le titre (saisie HAL).
    MetadataCorrectionRule.TITLE_ISBN_TO_BOOK_REVIEW: {
        "applies_to": {
            "doc_type": frozenset({DocType.ARTICLE, DocType.REVIEW, DocType.OTHER}),
            "title_regex": _ISBN_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.BOOK_REVIEW},
    },
    # Titre terminé par « AAAA, N p. » + mêmes types que la règle ISBN ⇒ `book_review`. Moins sûre, elle suit la règle ISBN.
    MetadataCorrectionRule.TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW: {
        "applies_to": {
            "doc_type": frozenset({DocType.ARTICLE, DocType.REVIEW, DocType.OTHER}),
            "title_regex": _YEAR_PAGES_END_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.BOOK_REVIEW},
    },
    # Titre de recension ⇒ `book_review`. OpenAlex type souvent les recensions `preprint`.
    MetadataCorrectionRule.TITLE_RECENSION_TO_BOOK_REVIEW: {
        "applies_to": {
            "doc_type": frozenset(
                {DocType.ARTICLE, DocType.REVIEW, DocType.OTHER, DocType.PREPRINT}
            ),
            "title_regex": _RECENSION_TITLE_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.BOOK_REVIEW},
    },
    # Revue de données + doc_type `article` ⇒ `data_paper`. Les sources typent `article` les data papers de ces revues. Évaluée après les règles de titre : un erratum ou un éditorial d'une revue de données garde son type.
    MetadataCorrectionRule.SERIAL_TYPE_DATA_JOURNAL_TO_DATA_PAPER: {
        "applies_to": {
            "serial_type": SerialType.DATA_JOURNAL,
            "doc_type": DocType.ARTICLE,
        },
        "applies_correction": {"doc_type": DocType.DATA_PAPER},
    },
}

_FIELDS = frozenset(f.name for f in fields(MetadataForCorrection))


def _check_predicate(source_record: MetadataForCorrection, key: str, value: object) -> bool:
    """Vrai si les faits vérifient le prédicat `key` de valeur `value` (`_AppliesTo`)."""
    if key == "doc_type":
        doc_type = (source_record.doc_type or "").lower()
        if isinstance(value, frozenset):
            return doc_type in value
        return doc_type == value
    if key == "doc_type_not_in":
        assert isinstance(value, frozenset)
        return (source_record.doc_type or "").lower() not in value
    if key == "author_count_max":
        assert isinstance(value, int)
        return source_record.author_count is not None and source_record.author_count <= value
    if key == "group_title":
        assert isinstance(value, frozenset)
        return (source_record.group_title or "").lower() in value
    if key == "url_contains":
        assert isinstance(value, str)
        return any(value in (u or "") for u in (source_record.urls or ()))
    if key == "doi_contains":
        assert isinstance(value, str)
        return any(value in doi for doi in source_record.dois)
    if key == "title_prefix_normalized":
        assert isinstance(value, tuple)
        if not source_record.title:
            return False
        normalized = normalize_text(source_record.title)
        return any(normalized.startswith(p) for p in value)
    if key == "title_regex":
        assert isinstance(value, re.Pattern)
        return bool(source_record.title and value.search(source_record.title))
    if key == "serial_id_present":
        assert isinstance(value, bool)
        return (source_record.serial_id is not None) == value
    if key == "doi_prefix_not_in":
        assert isinstance(value, tuple)
        return any(doi.split("/", 1)[0] not in value for doi in source_record.dois)
    if key == "registrant_publisher_type":
        return value in source_record.registrant_publisher_types
    if key in _FIELDS:
        return bool(getattr(source_record, key) == value)
    raise ValueError(f"Prédicat inconnu : {key!r}")


def _rule_applies(source_record: MetadataForCorrection, rule_def: _RuleDefinition) -> bool:
    """Vrai si les faits vérifient tous les prédicats de la règle."""
    return all(_check_predicate(source_record, k, v) for k, v in rule_def["applies_to"].items())


def _correct_field(source_record: MetadataForCorrection, field: str) -> Correction[str] | None:
    """Renvoie la correction de `field` par la première règle de `_RULES` qui le corrige et s'applique."""
    for rule_id, rule_def in _RULES.items():
        if field not in rule_def["applies_correction"]:
            continue
        if _rule_applies(source_record, rule_def):
            return Correction(rule_def["applies_correction"][field], rule_id)
    return None


def effective_metadata(source_record: MetadataForCorrection) -> CorrectedFields:
    """Calcule la correction de `doc_type`. Une correction qui dépend d'une autre, comme un type corrigé selon le type de la revue rattachée, passe par l'ordre des sous-étapes de la phase `metadata_correction`."""
    return CorrectedFields(
        doc_type=_correct_field(source_record, "doc_type"),
    )


# Préfixes d'identifiants HAL des thèses (TEL) et des mémoires (DUMAS).
_DISSERTATION_HALID_PREFIXES = ("tel-", "dumas-")


def is_dissertation_identifier(identifier: SourceIdentifier) -> bool:
    """Vrai si l'identifiant est propre à une thèse ou un mémoire : NNT, ou identifiant HAL `tel-` ou `dumas-`. Il est erroné sur un enregistrement source corrigé en article (`THESIS_WITH_SERIAL_TO_ARTICLE`) : OpenAlex et ScanR réunissent parfois une thèse et son article, avec les identifiants de la thèse."""
    if identifier.id_type is SourceIdentifierType.NNT:
        return True
    return identifier.id_type is SourceIdentifierType.HAL_ID and identifier.value.startswith(
        _DISSERTATION_HALID_PREFIXES
    )


def origin_doc_type_correction(
    doc_type: str | None, origin_doc_type: str | None
) -> Correction[str] | None:
    """Renvoie la correction de type d'un enregistrement source ScanR issu d'un dépôt HAL : il prend le type corrigé de ce dépôt.

    Args:
        origin_doc_type: type corrigé du dépôt HAL, `None` pour un enregistrement source issu d'aucun dépôt HAL ou pour un dépôt absent.
    """
    if origin_doc_type is None or origin_doc_type == doc_type:
        return None
    return Correction(origin_doc_type, MetadataCorrectionRule.SCANR_FROM_HAL_TO_HAL_TYPE)
