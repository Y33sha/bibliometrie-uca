"""Correction des métadonnées canoniques.

Expose `effective_metadata`, fonction pure qui applique des règles de correction sur les valeurs d'une publication source, à partir d'une vue de lecture `SourcePublicationWithJournalView` qui porte les champs de la SP **plus** des champs joints depuis `journals` (`journal_type`, `oa_model`, `apc_amount`). C'est cette vue qui rend la fonction capable d'appliquer aussi bien les règles SP-intrinsèques (URL) que les règles journal-dépendantes, sans threader de repo.

Distincte de l'agrégation (`aggregation.py` arbitre entre sources) et du normalizer (qui ne mute pas `source_publications`, trace inviolable des sources). Les corrections s'appliquent sur le canonique via `refresh_from_sources` et sur la SP entrante au moment du matching, pour que la dédup matche sur les valeurs corrigées.

Architecture : chaque règle est une fonction pure `_<name>(sp) -> Correction[str] | None` locale à ce module. Les règles actives sont enregistrées dans une tuple par champ corrigé (`_DOC_TYPE_RULES` aujourd'hui ; futur `_OA_STATUS_RULES`, `_JOURNAL_ID_RULES` selon les chantiers). `_correct_<field>` parcourt sa tuple dans l'ordre et retourne la première correction qui s'applique — l'ordre du tuple traduit la priorité intra-champ (signaux forts d'abord : URL > journal_type > titre).

Cascade entre champs (ordre des dépendances) : `journal_id` → `doc_type` → `oa_status`. Le membre `MetadataCorrectionRule` qui a produit la correction est inscrit dans `publications.meta.<field>_corrected_by` par le caller, pour tracer la correction.
"""

import re
from collections.abc import Callable
from enum import StrEnum
from typing import NamedTuple

from domain.normalize import normalize_text
from domain.source_publications.views import SourcePublicationWithJournalView


class MetadataCorrectionRule(StrEnum):
    """Identifiants des règles de correction figées. Une règle = un membre.

    Convention de nommage : `INPUT_CONDITION_TO_OUTPUT`. Le membre est inscrit dans `publications.meta.<field>_corrected_by` au moment où la règle est appliquée — c'est la trace d'audit consultable pour le re-run ciblé et l'affichage UI.
    """

    THESES_FR_URL_TO_THESIS = "THESES_FR_URL_TO_THESIS"
    DUMAS_URL_TO_MEMOIR = "DUMAS_URL_TO_MEMOIR"
    JOURNAL_TYPE_MEDIA_TO_MEDIA = "JOURNAL_TYPE_MEDIA_TO_MEDIA"
    JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER = "JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER"
    JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT = "JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT"
    TITLE_MEDIA_PREFIX_TO_MEDIA = "TITLE_MEDIA_PREFIX_TO_MEDIA"
    TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET = "TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET"
    TITLE_ERRATUM_PREFIX_TO_ERRATUM = "TITLE_ERRATUM_PREFIX_TO_ERRATUM"
    TITLE_RETRACTION_PREFIX_TO_RETRACTION = "TITLE_RETRACTION_PREFIX_TO_RETRACTION"
    TITLE_ISBN_TO_BOOK_REVIEW = "TITLE_ISBN_TO_BOOK_REVIEW"
    TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW = "TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW"


class Correction[T](NamedTuple):
    """Une valeur corrigée + la règle qui l'a produite."""

    value: T
    rule: MetadataCorrectionRule


class CorrectedFields(NamedTuple):
    """Résultat de `effective_metadata` : pour chaque champ, soit `None` (pas de correction), soit un `Correction` (valeur corrigée + règle d'origine).

    Ordre des champs aligné sur la cascade interne (journal_id d'abord, oa_status en dernier).
    """

    journal_id: Correction[int] | None = None
    doc_type: Correction[str] | None = None
    oa_status: Correction[str] | None = None

    def is_empty(self) -> bool:
        """True si aucune correction n'est portée — la fast-path des callers pour la majorité des SPs en régime."""
        return self.journal_id is None and self.doc_type is None and self.oa_status is None


# ── Règles individuelles de `doc_type` ───────────────────────────────
# Chaque règle = fonction pure `(SourcePublicationWithJournalView) -> Correction[str] | None`.
# Constantes (préfixes, whitelists, patterns) regroupées juste au-dessus de la règle qui les consomme.
# Le tuple `_DOC_TYPE_RULES` en bas de section fige l'ordre de la cascade.


_THESES_FR_URL_MARKER = "theses.fr/"


def _theses_fr_url_to_thesis(sp: SourcePublicationWithJournalView) -> Correction[str] | None:
    """theses.fr fait autorité sur les thèses françaises. Inconditionnel sur le `doc_type` brut : OpenAlex classe parfois ces thèses en `article` ou `dissertation`."""
    if any(_THESES_FR_URL_MARKER in (u or "") for u in sp.urls):
        return Correction("thesis", MetadataCorrectionRule.THESES_FR_URL_TO_THESIS)
    return None


_DUMAS_URL_MARKER = "dumas."


def _dumas_url_to_memoir(sp: SourcePublicationWithJournalView) -> Correction[str] | None:
    """DUMAS héberge des mémoires de master qu'OpenAlex classe à tort en `dissertation`. Whitelist `dissertation` pour ne pas dégrader les rares cas DUMAS de vraies thèses."""
    if (sp.doc_type or "").lower() == "dissertation" and any(
        _DUMAS_URL_MARKER in (u or "") for u in sp.urls
    ):
        return Correction("memoir", MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR)
    return None


def _journal_type_media_to_media(
    sp: SourcePublicationWithJournalView,
) -> Correction[str] | None:
    """Journal typé `media` (typage manuel admin) ⇒ `media` quel que soit le `doc_type` brut."""
    if sp.journal_type == "media":
        return Correction("media", MetadataCorrectionRule.JOURNAL_TYPE_MEDIA_TO_MEDIA)
    return None


# Whitelist restreinte à `{article, book_chapter}` : ce sont les classifications par défaut que les normalizers donnent aux papiers de conférence quand l'éditeur du journal d'actes est classique. `book` est exclu : un volume entier d'actes peut légitimement rester `book`.
_PROCEEDINGS_JOURNAL_APPLIES_TO = frozenset({"article", "book_chapter"})


def _journal_type_proceedings_to_conference_paper(
    sp: SourcePublicationWithJournalView,
) -> Correction[str] | None:
    """Journal d'actes + `doc_type` ∈ `_PROCEEDINGS_JOURNAL_APPLIES_TO` ⇒ `conference_paper`."""
    if sp.journal_type == "proceedings" and sp.doc_type in _PROCEEDINGS_JOURNAL_APPLIES_TO:
        return Correction(
            "conference_paper",
            MetadataCorrectionRule.JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER,
        )
    return None


# Whitelist `{article, other}` : les SPs OA/CrossRef d'une publi hébergée sur un serveur de preprints sont classées `article` (par mapping CrossRef `journal-article` ou par arbitrage canonique qui efface le `preprint` brut OA) ou `other`. Les types légitimes (`dataset`, `software`, `poster`) éventuellement présents sur ces plateformes restent inchangés.
_PREPRINT_SERVER_JOURNAL_APPLIES_TO = frozenset({"article", "other"})


def _journal_type_preprint_server_to_preprint(
    sp: SourcePublicationWithJournalView,
) -> Correction[str] | None:
    """Journal typé `preprint_server` (arXiv, bioRxiv, ChemRxiv, EGUsphere, SSRN, …) + `doc_type` ∈ `_PREPRINT_SERVER_JOURNAL_APPLIES_TO` ⇒ `preprint`."""
    if sp.journal_type == "preprint_server" and sp.doc_type in _PREPRINT_SERVER_JOURNAL_APPLIES_TO:
        return Correction(
            "preprint", MetadataCorrectionRule.JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT
        )
    return None


# Patterns récurrents : « Interview … », « Podcast Émission radio … », « Reportage pour … ».
_MEDIA_TITLE_PREFIXES = ("interview", "reportage", "podcast")
# Whitelist étroite : ce sont les classifications par défaut des dépôts médias mal typés. Types-référents (thesis, book, …) épargnés ; `media` lui-même exclu (no-op naturel).
_MEDIA_TITLE_APPLIES_TO = frozenset({"article", "other"})


def _title_media_prefix_to_media(
    sp: SourcePublicationWithJournalView,
) -> Correction[str] | None:
    """Titre commençant par `interview`/`reportage`/`podcast` + `doc_type` ∈ `_MEDIA_TITLE_APPLIES_TO` ⇒ `media`. Pattern univoque et récurrent dans le corpus UCA."""
    if sp.doc_type not in _MEDIA_TITLE_APPLIES_TO:
        return None
    if any(normalize_text(sp.title).startswith(p) for p in _MEDIA_TITLE_PREFIXES):
        return Correction("media", MetadataCorrectionRule.TITLE_MEDIA_PREFIX_TO_MEDIA)
    return None


# Préfixes (post-`normalize_text`) reconnus comme « contenu supplémentaire / données complémentaires ». Set ciblé plutôt que `'supplementary '` large pour éviter de matcher par accident un vrai article du type "Supplementary roles of X".
_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES = (
    "additional file",
    "supplementary material",
    "supplementary data",
    "supplementary information",
    "supplementary file",  # couvre "file" et "files"
    "supplementary dataset",  # couvre "dataset" et "datasets"
    "data from",
)
# `dataset` exclu du set (no-op naturel sur une publi déjà classée correctement).
_SUPPLEMENTARY_CONTENT_APPLIES_TO = frozenset({"article", "other"})


def _title_supplementary_content_to_dataset(
    sp: SourcePublicationWithJournalView,
) -> Correction[str] | None:
    """Titre commençant par un préfixe de `_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES` + `doc_type` ∈ `_SUPPLEMENTARY_CONTENT_APPLIES_TO` ⇒ `dataset`. DataCite et certaines plateformes (Dryad, Zenodo, IFREMER) exposent les fichiers complémentaires comme entités à part, classées `article` (faux) ou `other` (vague)."""
    if sp.doc_type not in _SUPPLEMENTARY_CONTENT_APPLIES_TO:
        return None
    if any(normalize_text(sp.title).startswith(p) for p in _SUPPLEMENTARY_CONTENT_TITLE_PREFIXES):
        return Correction("dataset", MetadataCorrectionRule.TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET)
    return None


# Pattern textuel très spécifique (mot exact en tête de titre, après normalisation), univoque dans les corpus observés.
_ERRATUM_TITLE_PREFIXES = ("erratum", "errata", "corrigendum")
# Whitelist restreinte aux types publication-like où un erratum est plausible. Les types-référents (thesis, book, book_chapter, memoir, hdr, dataset, …) sont épargnés.
_ERRATUM_APPLIES_TO = frozenset(
    {"article", "preprint", "review", "conference_paper", "data_paper", "letter", "other"}
)


def _title_erratum_prefix_to_erratum(
    sp: SourcePublicationWithJournalView,
) -> Correction[str] | None:
    """Titre commençant par `erratum`/`errata`/`corrigendum` + `doc_type` ∈ `_ERRATUM_APPLIES_TO` ⇒ `erratum`. OpenAlex reclasse fréquemment ces corrections en `article`/`preprint`/`data_paper`."""
    if sp.doc_type not in _ERRATUM_APPLIES_TO:
        return None
    if any(normalize_text(sp.title).startswith(p) for p in _ERRATUM_TITLE_PREFIXES):
        return Correction("erratum", MetadataCorrectionRule.TITLE_ERRATUM_PREFIX_TO_ERRATUM)
    return None


# Préfixes stricts : seuls « Retraction notice » et « Retraction note » (formulations canoniques utilisées par les éditeurs). Pas « retraction » seul, qui matcherait des titres comme « Retraction of consent in clinical trials ».
_RETRACTION_TITLE_PREFIXES = ("retraction notice", "retraction note")
_RETRACTION_APPLIES_TO = frozenset({"article", "other"})


def _title_retraction_prefix_to_retraction(
    sp: SourcePublicationWithJournalView,
) -> Correction[str] | None:
    """Titre commençant par un préfixe de `_RETRACTION_TITLE_PREFIXES` + `doc_type` ∈ `_RETRACTION_APPLIES_TO` ⇒ `retraction`."""
    if sp.doc_type not in _RETRACTION_APPLIES_TO:
        return None
    if any(normalize_text(sp.title).startswith(p) for p in _RETRACTION_TITLE_PREFIXES):
        return Correction(
            "retraction", MetadataCorrectionRule.TITLE_RETRACTION_PREFIX_TO_RETRACTION
        )
    return None


# Marqueurs de recension d'ouvrage (book review) détectés sur le titre brut.
# `_ISBN_PATTERN` : mention textuelle « ISBN » (mot entier) ou préfixe ISBN-13
# (97[89] suivi de 10–17 caractères chiffres/espaces/tirets). Signal très net.
_ISBN_PATTERN = re.compile(r"\bisbn\b|\b97[89][-\s0-9]{10,17}\b", re.IGNORECASE)
# `_YEAR_PAGES_END_PATTERN` : titre terminé par « (19|20)YY, N p[.|ages] »,
# forme classique d'une référence biblio injectée dans le champ titre par les
# saisisseurs HAL pour les comptes-rendus d'ouvrage. Plus bruité que ISBN.
_YEAR_PAGES_END_PATTERN = re.compile(
    r"(19|20)\d{2}[\s,.]+\d{1,4}\s*(pp|pages?|p)\.?\s*$", re.IGNORECASE
)
# Whitelist : recensions classées à tort dans ces types. `book`/`book_chapter` exclus (un ouvrage ou un chapitre peut légitimement porter son propre ISBN ou sa propre ref biblio dans le titre — saisie HAL fréquente).
_BOOK_REVIEW_APPLIES_TO = frozenset({"article", "review", "other"})


def _title_isbn_to_book_review(
    sp: SourcePublicationWithJournalView,
) -> Correction[str] | None:
    """Mention textuelle « ISBN » ou ISBN-13 nu dans le titre + `doc_type` ∈ `_BOOK_REVIEW_APPLIES_TO` ⇒ `book_review`."""
    if sp.doc_type not in _BOOK_REVIEW_APPLIES_TO or not sp.title:
        return None
    if _ISBN_PATTERN.search(sp.title):
        return Correction("book_review", MetadataCorrectionRule.TITLE_ISBN_TO_BOOK_REVIEW)
    return None


def _title_year_pages_end_to_book_review(
    sp: SourcePublicationWithJournalView,
) -> Correction[str] | None:
    """Titre se terminant par « (19|20)YY, N p[.|ages] » + `doc_type` ∈ `_BOOK_REVIEW_APPLIES_TO` ⇒ `book_review`. Évaluée après la règle ISBN (un titre porteur d'un ISBN explicite est attribué par celle-ci)."""
    if sp.doc_type not in _BOOK_REVIEW_APPLIES_TO or not sp.title:
        return None
    if _YEAR_PAGES_END_PATTERN.search(sp.title):
        return Correction("book_review", MetadataCorrectionRule.TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW)
    return None


# ── Cascade `doc_type` ──────────────────────────────────────────────
# Ordre = priorité : URL (signal le plus fort) → journal_type → titre. Les whitelists `_*_APPLIES_TO` sont calibrées pour être quasi disjointes entre règles d'une même famille, donc l'ordre intra-famille importe peu en pratique. La règle ISBN évaluée avant la règle année-pages : un titre porteur d'un ISBN explicite est plus fiable.

_DocTypeRule = Callable[[SourcePublicationWithJournalView], Correction[str] | None]

_DOC_TYPE_RULES: tuple[_DocTypeRule, ...] = (
    _theses_fr_url_to_thesis,
    _dumas_url_to_memoir,
    _journal_type_media_to_media,
    _journal_type_proceedings_to_conference_paper,
    _journal_type_preprint_server_to_preprint,
    _title_media_prefix_to_media,
    _title_supplementary_content_to_dataset,
    _title_erratum_prefix_to_erratum,
    _title_retraction_prefix_to_retraction,
    _title_isbn_to_book_review,
    _title_year_pages_end_to_book_review,
)


def _correct_doc_type(sp: SourcePublicationWithJournalView) -> Correction[str] | None:
    """Applique les règles `_DOC_TYPE_RULES` dans l'ordre ; première qui matche gagne."""
    for rule in _DOC_TYPE_RULES:
        if (result := rule(sp)) is not None:
            return result
    return None


def effective_metadata(sp: SourcePublicationWithJournalView) -> CorrectedFields:
    """Applique la cascade de corrections sur les champs d'une `SourcePublicationWithJournalView`. Retourne un `CorrectedFields` (vide si aucune règle ne s'applique).

    Fonction pure : aucune I/O, aucun effet de bord. Les données journal/publisher consommées par les règles arrivent par la vue (champs joints à la lecture), pas via des entités passées en paramètre — c'est ce qui permet à la fonction de servir aussi bien la dédup (sur la SP entrante) que le refresh (sur les sources d'une publication).

    Cascade dans l'ordre des dépendances (`journal_id` → `doc_type` → `oa_status`) ; seul `doc_type` porte des règles à ce stade.
    """
    return CorrectedFields(doc_type=_correct_doc_type(sp))
