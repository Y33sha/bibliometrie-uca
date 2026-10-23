"""Correction des métadonnées par table de règles, pour un enregistrement source comme pour une publication.

`effective_metadata` applique les règles aux faits de `MetadataForCorrection`. Elle corrige `doc_type` et `oa_status`.

Une règle est un membre de `MetadataCorrectionRule` et son entrée dans `_RULES`. `applies_to` liste ses prédicats, tous requis. `applies_correction` donne la valeur cible de chaque champ corrigé. Pour un champ, la première règle de `_RULES` qui s'applique l'emporte.

Les prédicats sont les clés de `_AppliesTo`. Une clé qui nomme un champ de `MetadataForCorrection` teste l'égalité. Les autres clés ont leur branche dans `_check_predicate`.

Un fait inconnu vaut `None`, et les prédicats qui le testent sont faux. Une publication connaît seulement les faits de `MetadataForCorrection.for_publication`.
"""

import re
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import NamedTuple, TypedDict

from domain.journals.journal import JournalType, OaModel
from domain.normalize import normalize_text
from domain.publications.doc_types import DocType
from domain.publishers.publisher import PublisherType
from domain.source_records.external_ids import ExternalIdType
from domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class MetadataForCorrection:
    """Faits que lisent les règles de correction, pour un enregistrement source ou une publication.

    Un fait à `None` est inconnu, et un prédicat sur un fait inconnu est faux. Une publication renseigne seulement les champs que l'agrégation arbitre (`for_publication`) : les règles qui lisent un fait propre aux enregistrements sources ne s'appliquent pas à elle.

    Frozen : `hydrate_raw_view` produit une vue par `dataclasses.replace`.
    """

    title: str
    doc_type: str | None
    doi: str | None
    journal_id: int | None
    journal_type: str | None = None
    oa_status: str | None = None
    oa_model: str | None = None
    urls: list[str] | None = None
    # `embargo_until <= current_date`.
    embargo_expired: bool | None = None
    # L'enregistrement déclare la relation Crossref `is-preprint-of` : il est le preprint d'une autre œuvre.
    self_declared_preprint: bool | None = None
    # L'enregistrement nomme le congrès dont il est issu (Crossref `event`, ou `assertion` Springer).
    declares_conference: bool | None = None
    # Type de l'éditeur qui a déposé le préfixe du DOI (`doi_prefixes`).
    registrant_publisher_type: str | None = None
    # La monographie de l'enregistrement est un volume d'actes (`monographs.proceedings`).
    in_proceedings_volume: bool | None = None
    # Forme de présentation d'un `posted-content` Crossref (`oral`, `pico`, `display`).
    group_title: str | None = None
    # La revue rattachée est diamant (marquée `diamond`, ou dans le DOAJ sans APC ni autres frais).
    journal_diamond: bool | None = None
    source: str | None = None
    # `source_records.author_count` : contributions sources d'auteur non collectives.
    author_count: int | None = None

    @classmethod
    def for_publication(
        cls,
        *,
        title: str,
        doc_type: str | None,
        doi: str | None,
        journal_id: int | None,
        journal_type: str | None,
    ) -> "MetadataForCorrection":
        """Faits d'une publication : les champs que l'agrégation arbitre, et le type de sa revue."""
        return cls(
            title=title,
            doc_type=doc_type,
            doi=doi,
            journal_id=journal_id,
            journal_type=journal_type,
        )


class MetadataCorrectionRule(StrEnum):
    """Identifiants des règles de correction figées. Une règle = un membre.

    Convention de nommage : `INPUT_CONDITION_TO_OUTPUT`. Le membre est tracé par le caller au moment où la règle est appliquée (`corrections.<champ>.corrected_by` de `source_records` comme de `publications`) — trace d'audit consultable pour le re-run ciblé et l'affichage UI.
    """

    THESES_FR_URL_TO_THESIS = "THESES_FR_URL_TO_THESIS"
    DUMAS_URL_TO_MEMOIR = "DUMAS_URL_TO_MEMOIR"
    THESIS_WITH_JOURNAL_TO_ARTICLE = "THESIS_WITH_JOURNAL_TO_ARTICLE"
    JOURNAL_TYPE_MEDIA_TO_MEDIA = "JOURNAL_TYPE_MEDIA_TO_MEDIA"
    JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER = "JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER"
    CONFERENCE_DECLARED_TO_CONFERENCE_PAPER = "CONFERENCE_DECLARED_TO_CONFERENCE_PAPER"
    PROCEEDINGS_VOLUME_TO_CONFERENCE_PAPER = "PROCEEDINGS_VOLUME_TO_CONFERENCE_PAPER"
    PRESENTATION_ORAL_TO_CONFERENCE = "PRESENTATION_ORAL_TO_CONFERENCE"
    PRESENTATION_DISPLAY_TO_POSTER = "PRESENTATION_DISPLAY_TO_POSTER"
    DOI_REGISTRANT_MEDIA_TO_MEDIA = "DOI_REGISTRANT_MEDIA_TO_MEDIA"
    CROSSREF_AUTHORLESS_VOLUME_TITLE_TO_PROCEEDINGS = (
        "CROSSREF_AUTHORLESS_VOLUME_TITLE_TO_PROCEEDINGS"
    )
    CROSSREF_VOLUME_TITLE_PREFIX_TO_PROCEEDINGS = "CROSSREF_VOLUME_TITLE_PREFIX_TO_PROCEEDINGS"
    JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT = "JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT"
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
    DOI_FIGSHARE_COLLECTION_TO_DATASET = "DOI_FIGSHARE_COLLECTION_TO_DATASET"
    EMBARGO_EXPIRED_TO_GREEN = "EMBARGO_EXPIRED_TO_GREEN"
    GOLD_DIAMOND_JOURNAL_TO_DIAMOND = "GOLD_DIAMOND_JOURNAL_TO_DIAMOND"
    HYBRID_DIAMOND_JOURNAL_TO_DIAMOND = "HYBRID_DIAMOND_JOURNAL_TO_DIAMOND"
    DIAMOND_OUTSIDE_DIAMOND_JOURNAL_TO_GOLD = "DIAMOND_OUTSIDE_DIAMOND_JOURNAL_TO_GOLD"
    HYBRID_FULL_OA_TO_GOLD = "HYBRID_FULL_OA_TO_GOLD"
    SCANR_FROM_HAL_TO_HAL_TYPE = "SCANR_FROM_HAL_TO_HAL_TYPE"


class Correction[T](NamedTuple):
    """Une valeur corrigée + la règle qui l'a produite."""

    value: T
    rule: MetadataCorrectionRule


class CorrectedFields(NamedTuple):
    """Résultat de `effective_metadata` : pour chaque champ, soit `None` (pas de correction), soit un `Correction` (valeur corrigée + règle d'origine).

    Ordre des champs aligné sur la cascade interne (doc_type puis oa_status).
    """

    doc_type: Correction[str] | None = None
    oa_status: Correction[str] | None = None


# ── Constantes (préfixes, patterns) référencées par les règles ──────────

# Pattern textuel récurrent dans le corpus UCA pour les interventions média.
_MEDIA_TITLE_PREFIXES = ("interview", "reportage", "podcast")

# Préfixes (post-`normalize_text`) reconnus comme « contenu supplémentaire ». Set ciblé plutôt que `'supplementary '` large pour éviter de matcher par accident un vrai article du type "Supplementary roles of X".
_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES = (
    "additional file",
    "supplementary material",
    "supplementary data",
    "supplementary information",
    "supplementary file",  # couvre "file" et "files"
    "supplementary dataset",  # couvre "dataset" et "datasets"
    "data from",
)

# Pattern textuel très spécifique, univoque dans les corpus observés.
_ERRATUM_TITLE_PREFIXES = (
    DocType.ERRATUM,
    "errata",
    "corrigendum",
    "author correction",
    "publisher correction",
)

# Préfixes stricts : seules les formulations canoniques utilisées par les éditeurs. Pas « retraction » seul, qui matcherait des titres comme « Retraction of consent in clinical trials ».
_RETRACTION_TITLE_PREFIXES = ("retraction notice", "retraction note")

# « Editorial: <titre> » (Frontiers & co.). Le « : » est discriminant : `normalize_text`
# efface la ponctuation, donc un préfixe nu « editorial » matcherait « Editorial Board »,
# « Editorial comment »… → regex ancrée sur le titre brut (audit : motif univoque).
_EDITORIAL_PREFIX_PATTERN = re.compile(r"^\s*editorial\s*:", re.IGNORECASE)
# « Letter: <titre> » (courrier à l'éditeur / research letter).
_LETTER_PREFIX_PATTERN = re.compile(r"^\s*letter\s*:", re.IGNORECASE)
# « systematic review(s) » en tête de titre OU en sous-titre (après « : »), forme
# document-type univoque. Ancré pour exclure les mentions au fil du titre (étude primaire
# « …cohort, and a systematic review », protocole de revue, reply) — audit : ~100% reviews.
_SYSTEMATIC_REVIEW_PATTERN = re.compile(r"(^|:\s*)(a\s+)?systematic reviews?\b", re.IGNORECASE)

# Marqueurs de recension d'ouvrage détectés sur le titre brut.
# `_ISBN_PATTERN` : mention « ISBN » (mot entier) ou préfixe ISBN-13 (97[89] suivi de 10–17 caractères chiffres/espaces/tirets). Signal très net.
_ISBN_PATTERN = re.compile(r"\bisbn\b|\b97[89][-\s0-9]{10,17}\b", re.IGNORECASE)
# `_YEAR_PAGES_END_PATTERN` : titre terminé par « (19|20)YY, N p[.|ages] », forme classique d'une référence biblio injectée dans le champ titre par les saisisseurs HAL pour les comptes-rendus d'ouvrage. Plus bruité que ISBN.
_YEAR_PAGES_END_PATTERN = re.compile(
    r"(19|20)\d{2}[\s,.]+\d{1,4}\s*(pp|pages?|p)\.?\s*$", re.IGNORECASE
)
# `_RECENSION_TITLE_PATTERN` : titre commençant par « Recension » (« Recension : … », « Recension de … », « Recensions »), ou par « Compte(s) rendu(s) : » avec deux-points immédiat. Marqueurs univoques de recension d'ouvrage en usage académique français, souvent typés article/other/preprint par les sources. Le deux-points immédiat après « compte(s) rendu(s) » écarte les rapports (« Compte rendu de mission : … », « Compte rendu de la soutenance d'HDR … ») qui ne sont pas des recensions.
_RECENSION_TITLE_PATTERN = re.compile(r"^\s*(recension|comptes?\s+rendus?\s*:)", re.IGNORECASE)

# Vocabulaire d'un volume d'actes ou d'un recueil de résumés, n'importe où dans le titre. Seul, il désigne aussi des articles (discours présidentiel, introduction éditoriale) : la règle qui le lit exige un enregistrement sans auteur.
_VOLUME_TITLE_PATTERN = re.compile(
    r"\b(proceedings|abstracts?|congress|congrès|congres|meeting|symposium|conference|colloque"
    r"|communications\s+affich[ée]es|poster\s+presentations|posters)\b",
    re.IGNORECASE,
)
# Début de titre d'un volume. « Abstract » au singulier en est exclu : « Abstract 4007: … » est un résumé isolé.
_VOLUME_TITLE_PREFIX_PATTERN = re.compile(
    r"^\s*(proceedings|abstracts|book\s+of\s+abstracts|abstract\s+book)\b", re.IGNORECASE
)

# Préfixes DOI des registres de thèses : un DOI émis par ces registres est le DOI *propre* de la
# thèse, pas celui d'une version publiée. `10.70675` = ABES (Agence Bibliographique de
# l'Enseignement Supérieur), résolu via `doi_prefixes` (publisher « agence bibliographique de l
# enseignement superieur »). Ensemble volontairement incomplet : les thèses déposées en repository
# institutionnel (Wageningen, Karlsruhe…) ont des préfixes variés non listés. Les généraliser suppose
# une nature de registrant (éditeur, repository ou registre) dans `doi_prefixes`.
_THESIS_REGISTRY_DOI_PREFIXES = ("10.70675",)


# ── Mini-DSL des règles ─────────────────────────────────────────────────


class _AppliesTo(TypedDict, total=False):
    """Prédicats d'une règle, tous AND-és.

    Une clé au nom d'un champ de `MetadataForCorrection` est une égalité sur ce champ. Les autres :

    - `doc_type` : `str` ou `frozenset[str]`, comparé en minuscules. Limite la règle aux types plausibles.
    - `group_title` : `frozenset[str]`, comparé en minuscules.
    - `url_contains` : sous-chaîne d'au moins une des `urls`.
    - `doi_contains` : sous-chaîne du DOI.
    - `title_prefix_normalized` : préfixes de `normalize_text(title)`.
    - `title_regex` : motif cherché dans le titre.
    - `journal_id_present` : présence d'un `journal_id`.
    - `doi_prefix_not_in` : le DOI existe et son préfixe est hors du tuple.
    - `author_count_max` : `author_count` connu et au plus égal à la valeur.
    """

    doc_type: str | frozenset[str]
    journal_type: str
    oa_model: str
    url_contains: str
    doi_contains: str
    title_prefix_normalized: tuple[str, ...]
    title_regex: re.Pattern[str]
    journal_id_present: bool
    doi_prefix_not_in: tuple[str, ...]
    oa_status: str
    embargo_expired: bool
    self_declared_preprint: bool
    declares_conference: bool
    registrant_publisher_type: str
    in_proceedings_volume: bool
    group_title: frozenset[str]
    journal_diamond: bool
    source: str
    author_count_max: int


class _AppliesCorrection(TypedDict, total=False):
    """Champ corrigé et sa valeur cible."""

    doc_type: str
    oa_status: str


class _RuleDefinition(TypedDict):
    applies_to: _AppliesTo
    applies_correction: _AppliesCorrection


# Whitelist récurrente : types plausibles pour une reclassification par titre.
_ARTICLE_OR_OTHER = frozenset({DocType.ARTICLE, DocType.OTHER})


# ── Table des règles ────────────────────────────────────────────────────
# Ordre = priorité de la cascade (signaux forts d'abord : URL > journal_type > titre). Les whitelists `doc_type` sont calibrées pour être quasi disjointes entre règles d'une même famille, donc l'ordre intra-famille importe peu en pratique. La règle ISBN évaluée avant la règle année-pages : un titre porteur d'un ISBN explicite est plus fiable.

_RULES: dict[MetadataCorrectionRule, _RuleDefinition] = {
    # theses.fr fait autorité sur les thèses françaises (OpenAlex classe parfois ces thèses en `article` ou `dissertation`). Gardée par `journal_id_present: False` : un enregistrement source theses.fr AVEC un journal_id est une conflation thèse↔article publié — c'est l'aspect article qui prime (`THESIS_WITH_JOURNAL_TO_ARTICLE`), pas l'URL theses.fr. La règle corrige donc en `thesis` les seuls enregistrements sources theses.fr **sans** journal.
    MetadataCorrectionRule.THESES_FR_URL_TO_THESIS: {
        "applies_to": {"url_contains": "theses.fr/", "journal_id_present": False},
        "applies_correction": {"doc_type": DocType.THESIS},
    },
    # DUMAS (dumas.ccsd) n'héberge que des mémoires : URL-only, même garde `journal_id_present: False` que theses.fr (un enregistrement source DUMAS avec journal_id = article publié → prime sur le mémoire).
    MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR: {
        "applies_to": {"url_contains": "dumas.ccsd", "journal_id_present": False},
        "applies_correction": {"doc_type": DocType.MEMOIR},
    },
    # Famille thèse + `journal_id` présent ⇒ `article`, SAUF si le DOI est celui d'un registre de
    # thèses (`doi_prefix_not_in`). Une vraie thèse a un DOI ABES (ou pas de DOI) ; un DOI d'éditeur
    # signe au contraire la version publiée. Le `doc_type=thesis` + `journal_id` + DOI éditeur est
    # donc un article publié (mistype d'OpenAlex/ScanR, ou conflation thèse↔version publiée mergées
    # par titre) → `article`. Avec un DOI ABES ou aucun DOI, le `journal_id` est parasite (la version
    # publiée d'une conflation) : le type reste thèse, le nettoyage du journal_id relève des relations.
    # Placée APRÈS les règles URL : un enregistrement source theses.fr/DUMAS reste thèse/mémoire (l'URL est le signal
    # fort). Le nullage des clés-thèse (NNT, hal_id `tel-`/`dumas-`) de la conflation est traité à
    # part (mutation `external_ids`, hors DSL colonne).
    MetadataCorrectionRule.THESIS_WITH_JOURNAL_TO_ARTICLE: {
        "applies_to": {
            "doc_type": frozenset({DocType.THESIS, DocType.ONGOING_THESIS, DocType.MEMOIR}),
            "journal_id_present": True,
            "doi_prefix_not_in": _THESIS_REGISTRY_DOI_PREFIXES,
        },
        "applies_correction": {"doc_type": DocType.ARTICLE},
    },
    # Journal typé `media` (typage manuel admin) ⇒ `media` quel que soit le `doc_type`.
    MetadataCorrectionRule.JOURNAL_TYPE_MEDIA_TO_MEDIA: {
        "applies_to": {"journal_type": JournalType.MEDIA},
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
    # Journal d'actes + doc_type plausible ⇒ `conference_paper`. `book` exclu : un volume entier d'actes peut légitimement rester `book`.
    MetadataCorrectionRule.JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER: {
        "applies_to": {
            "journal_type": JournalType.PROCEEDINGS,
            "doc_type": frozenset({DocType.ARTICLE, DocType.BOOK_CHAPTER}),
        },
        "applies_correction": {"doc_type": DocType.CONFERENCE_PAPER},
    },
    # Article ou chapitre d'un volume d'actes (sa monographie) ⇒ `conference_paper`. Le volume d'actes remplace le recueil de `journals` comme conteneur des articles de congrès.
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
    # Serveur de preprints (arXiv, bioRxiv, ChemRxiv, EGUsphere, SSRN, …) + doc_type ∈ {article, other} ⇒ `preprint`.
    MetadataCorrectionRule.JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT: {
        "applies_to": {
            "journal_type": JournalType.PREPRINT_SERVER,
            "doc_type": _ARTICLE_OR_OTHER,
        },
        "applies_correction": {"doc_type": DocType.PREPRINT},
    },
    # L'enregistrement source déclare lui-même une relation `is-preprint-of` (Crossref `source_extras.relation`) : il EST
    # le preprint, signal source-autoritaire et indépendant du `doc_type` (donc acyclique vis-à-vis
    # des relations dérivées du type). Sans whitelist `doc_type` : la déclaration prime, y compris
    # quand Crossref n'a pas typé le record (`doc_type` nul → l'arbitrage prenait `article`
    # d'OpenAlex faute de mieux ; Crossref étant prioritaire, le `preprint` corrigé gagne).
    MetadataCorrectionRule.PREPRINT_RELATION_TO_PREPRINT: {
        "applies_to": {"self_declared_preprint": True},
        "applies_correction": {"doc_type": DocType.PREPRINT},
    },
    # Titre `interview`/`reportage`/`podcast` + `doc_type` ∈ {article, other} ⇒ `media`. Patterns univoques et récurrents dans le corpus UCA.
    MetadataCorrectionRule.TITLE_MEDIA_PREFIX_TO_MEDIA: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "title_prefix_normalized": _MEDIA_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": DocType.MEDIA},
    },
    # Collection figshare (`10.6084/m9.figshare.c.<id>` — le `.c.` marque un bundle de suppléments, vs un item `m9.figshare.<id>`) + doc_type ∈ {article, other} ⇒ `dataset`. Le titre d'une collection = le titre du papier parent, donc inattrapable par la règle titre supplément → discrimination par DOI. Fallback hardcodé ; une détection RA DataCite (figshare-as-client) généraliserait aux instances figshare sous d'autres préfixes.
    MetadataCorrectionRule.DOI_FIGSHARE_COLLECTION_TO_DATASET: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "doi_contains": "m9.figshare.c.",
        },
        "applies_correction": {"doc_type": DocType.DATASET},
    },
    # Titre suppléments / données complémentaires + doc_type ∈ {article, other} ⇒ `dataset`. DataCite et certaines plateformes (Dryad, Zenodo, IFREMER) exposent les fichiers complémentaires comme entités à part. `dataset` lui-même exclu (no-op naturel).
    MetadataCorrectionRule.TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "title_prefix_normalized": _SUPPLEMENTARY_CONTENT_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": DocType.DATASET},
    },
    # Titre `erratum`/`errata`/`corrigendum` + doc_type publication-like ⇒ `erratum`. OpenAlex reclasse fréquemment ces corrections en `article`/`preprint`/`data_paper`. Types-référents (thesis, book, dataset, …) épargnés.
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
    # Titre `retraction notice/note` + doc_type ∈ {article, other} ⇒ `retraction`. Préfixes stricts pour éviter un faux positif sur un article *sur* la rétractation.
    MetadataCorrectionRule.TITLE_RETRACTION_PREFIX_TO_RETRACTION: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "title_prefix_normalized": _RETRACTION_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": DocType.RETRACTION},
    },
    # Titre « Editorial: … » + doc_type ∈ {article, other} ⇒ `editorial`. Frontiers & co.
    # publient les éditoriaux sous ce préfixe, qu'OpenAlex/ScanR/CrossRef typent souvent
    # `article`. Ancré sur le « : » (cf. `_EDITORIAL_PREFIX_PATTERN`).
    MetadataCorrectionRule.TITLE_EDITORIAL_PREFIX_TO_EDITORIAL: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "title_regex": _EDITORIAL_PREFIX_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.EDITORIAL},
    },
    # Titre « Letter: … » + doc_type ∈ {article, other} ⇒ `letter`. Courriers à l'éditeur /
    # research letters mal typés `article`.
    MetadataCorrectionRule.TITLE_LETTER_PREFIX_TO_LETTER: {
        "applies_to": {
            "doc_type": _ARTICLE_OR_OTHER,
            "title_regex": _LETTER_PREFIX_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.LETTER},
    },
    # « systematic review » en tête ou en sous-titre + doc_type ∈ {article} ⇒ `review`.
    # Ancré (cf. `_SYSTEMATIC_REVIEW_PATTERN`) pour ne prendre que la forme document-type, pas
    # les mentions au fil du titre. La whitelist épargne conference_paper/preprint/poster/
    # memoir/dataset (une revue systématique peut légitimement être l'un d'eux).
    MetadataCorrectionRule.TITLE_SYSTEMATIC_REVIEW_TO_REVIEW: {
        "applies_to": {
            "doc_type": frozenset({DocType.ARTICLE}),
            "title_regex": _SYSTEMATIC_REVIEW_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.REVIEW},
    },
    # Titre porteur d'un ISBN explicite + doc_type ∈ {article, review, other} ⇒ `book_review`. `book`/`book_chapter` exclus (un ouvrage ou un chapitre peut légitimement porter son propre ISBN dans le titre — saisie HAL fréquente).
    MetadataCorrectionRule.TITLE_ISBN_TO_BOOK_REVIEW: {
        "applies_to": {
            "doc_type": frozenset({DocType.ARTICLE, DocType.REVIEW, DocType.OTHER}),
            "title_regex": _ISBN_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.BOOK_REVIEW},
    },
    # Titre terminé par « (19|20)YY, N p[.|ages] » + même whitelist que la règle ISBN ⇒ `book_review`. Plus bruité que ISBN, évaluée après.
    MetadataCorrectionRule.TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW: {
        "applies_to": {
            "doc_type": frozenset({DocType.ARTICLE, DocType.REVIEW, DocType.OTHER}),
            "title_regex": _YEAR_PAGES_END_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.BOOK_REVIEW},
    },
    # Titre commençant par « Recension » ou « Compte(s) rendu(s) : » ⇒ `book_review`. Marqueurs univoques en usage académique français ; `preprint` inclus dans la whitelist (typage OpenAlex fréquent). `book`/`book_chapter` épargnés : la recension est l'article, pas l'ouvrage recensé.
    MetadataCorrectionRule.TITLE_RECENSION_TO_BOOK_REVIEW: {
        "applies_to": {
            "doc_type": frozenset(
                {DocType.ARTICLE, DocType.REVIEW, DocType.OTHER, DocType.PREPRINT}
            ),
            "title_regex": _RECENSION_TITLE_PATTERN,
        },
        "applies_correction": {"doc_type": DocType.BOOK_REVIEW},
    },
    # Embargo HAL levé : un dépôt typé `embargoed` dont la date de fin est passée
    # (`embargo_expired`, calculé à la lecture) devient `green`. Promotion à l'échéance sans
    # ré-import HAL — seule règle date-dépendante (la date est lue en SQL, hors de la
    # fonction pure). Trace dans `corrections.oa_status` ; corrige un champ orthogonal au
    # `doc_type`, donc aucun chaînage avec les règles ci-dessus.
    MetadataCorrectionRule.EMBARGO_EXPIRED_TO_GREEN: {
        "applies_to": {"oa_status": "embargoed", "embargo_expired": True},
        "applies_correction": {"oa_status": "green"},
    },
    # Le diamant est une propriété de la revue : marquée `diamond`, ou dans le DOAJ sans APC ni autres frais.
    # Un article `gold` ou `hybrid` d'une revue diamant est `diamond`. Un `diamond` d'OpenAlex hors revue diamant est `gold`.
    # Ces règles précèdent `HYBRID_FULL_OA_TO_GOLD` : une revue diamant classée full OA reste diamant.
    MetadataCorrectionRule.GOLD_DIAMOND_JOURNAL_TO_DIAMOND: {
        "applies_to": {"oa_status": "gold", "journal_diamond": True},
        "applies_correction": {"oa_status": "diamond"},
    },
    MetadataCorrectionRule.HYBRID_DIAMOND_JOURNAL_TO_DIAMOND: {
        "applies_to": {"oa_status": "hybrid", "journal_diamond": True},
        "applies_correction": {"oa_status": "diamond"},
    },
    MetadataCorrectionRule.DIAMOND_OUTSIDE_DIAMOND_JOURNAL_TO_GOLD: {
        "applies_to": {"oa_status": "diamond", "journal_diamond": False},
        "applies_correction": {"oa_status": "gold"},
    },
    # Un `hybrid` posé par défaut au normalize (avant l'enrichissement des revues) dans
    # une revue full-OA est en réalité `gold` : `hybrid` sort des statuts attendus pour
    # `oa_model = full_oa`. Champ orthogonal au `doc_type`, aucun chaînage avec les autres règles.
    MetadataCorrectionRule.HYBRID_FULL_OA_TO_GOLD: {
        "applies_to": {"oa_status": "hybrid", "oa_model": OaModel.FULL_OA},
        "applies_correction": {"oa_status": "gold"},
    },
}

# ── Moteur ──────────────────────────────────────────────────────────────

_FIELDS = frozenset(f.name for f in fields(MetadataForCorrection))


def _check_predicate(source_record: MetadataForCorrection, key: str, value: object) -> bool:
    """Évalue un prédicat (paire clé/valeur de `applies_to`) sur la `source_record`. Voir `_AppliesTo` pour la sémantique de chaque clé."""
    if key == "doc_type":
        doc_type = (source_record.doc_type or "").lower()
        if isinstance(value, frozenset):
            return doc_type in value
        return doc_type == value
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
        return value in (source_record.doi or "")
    if key == "title_prefix_normalized":
        assert isinstance(value, tuple)
        if not source_record.title:
            return False
        normalized = normalize_text(source_record.title)
        return any(normalized.startswith(p) for p in value)
    if key == "title_regex":
        assert isinstance(value, re.Pattern)
        return bool(source_record.title and value.search(source_record.title))
    if key == "journal_id_present":
        assert isinstance(value, bool)
        return (source_record.journal_id is not None) == value
    if key == "doi_prefix_not_in":
        assert isinstance(value, tuple)
        if not source_record.doi:
            return False
        return source_record.doi.split("/", 1)[0] not in value
    if key in _FIELDS:
        return bool(getattr(source_record, key) == value)
    raise ValueError(f"Prédicat inconnu : {key!r}")


def _rule_applies(source_record: MetadataForCorrection, rule_def: _RuleDefinition) -> bool:
    """True si tous les prédicats `applies_to` de la règle sont vérifiés (AND)."""
    return all(_check_predicate(source_record, k, v) for k, v in rule_def["applies_to"].items())


def _correct_field(source_record: MetadataForCorrection, field: str) -> Correction[str] | None:
    """Applique les règles `_RULES` dans l'ordre ; première qui corrige `field` et dont les prédicats matchent gagne."""
    for rule_id, rule_def in _RULES.items():
        if field not in rule_def["applies_correction"]:
            continue
        if _rule_applies(source_record, rule_def):
            return Correction(rule_def["applies_correction"][field], rule_id)
    return None


def effective_metadata(source_record: MetadataForCorrection) -> CorrectedFields:
    """Applique les corrections sur les champs d'un `MetadataForCorrection`. Retourne un `CorrectedFields` (vide si aucune règle ne s'applique).

    Fonction pure : aucune I/O, aucun effet de bord. Les données journal consommées par les règles arrivent par le contrat (champs joints à la lecture), pas via des entités passées en paramètre — ce qui permet à la fonction de servir aussi bien la dédup (sur la `source_record` entrante) que le refresh (sur la publication canonique).

    `doc_type` et `oa_status` sont corrigés **indépendamment** depuis la même vue : aucune règle de l'un ne lit la valeur corrigée de l'autre (`oa_status` est la promotion d'embargo, orthogonale au `doc_type`). Les dépendances inter-champ — un type corrigé selon le `journal_type` du journal rattaché — se résolvent par l'**ordre des sous-steps** de la phase (chacun re-lit l'état persisté du précédent), pas par un feed-forward intra-fonction.
    """
    return CorrectedFields(
        doc_type=_correct_field(source_record, "doc_type"),
        oa_status=_correct_field(source_record, "oa_status"),
    )


# Préfixes d'identifiants HAL propres aux dissertations : TEL (thèses en ligne) et DUMAS
# (mémoires/dissertations étudiantes). Un hal_id à ce préfixe n'est jamais celui d'un article.
_DISSERTATION_HALID_PREFIXES = ("tel-", "dumas-")


def strip_dissertation_keys(external_ids: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Retire d'un `external_ids` les clés propres aux **dissertations**, erronées sur une `source_record` article (conflation thèse↔article publié : OpenAlex/ScanR fusionnent une thèse et son article dans un seul enregistrement, en gardant le `nnt` / les hal_id `tel-`/`dumas-` de la thèse).

    Retire `nnt` et les `hal_id` préfixés `tel-`/`dumas-` (en conservant les autres hal_id, qui pointent l'article). Pur. Le caller n'appelle cette fonction que sur les `source_records` corrigées thèse→article (`THESIS_WITH_JOURNAL_TO_ARTICLE`).
    """
    result = {k: v for k, v in external_ids.items() if k != ExternalIdType.NNT}
    hal_ids = result.get(ExternalIdType.HAL_ID)
    if isinstance(hal_ids, list):
        kept = [
            h
            for h in hal_ids
            if not (isinstance(h, str) and h.startswith(_DISSERTATION_HALID_PREFIXES))
        ]
        if kept:
            result[ExternalIdType.HAL_ID] = kept
        else:
            result.pop(ExternalIdType.HAL_ID, None)
    return result


def origin_doc_type_correction(
    doc_type: str | None, origin_doc_type: str | None
) -> Correction[str] | None:
    """Un enregistrement source ScanR issu d'un dépôt HAL prend le type corrigé de ce dépôt. `origin_doc_type` : type corrigé du dépôt HAL, `None` si l'enregistrement source n'en est pas issu ou si le dépôt est absent."""
    if origin_doc_type is None or origin_doc_type == doc_type:
        return None
    return Correction(origin_doc_type, MetadataCorrectionRule.SCANR_FROM_HAL_TO_HAL_TYPE)
