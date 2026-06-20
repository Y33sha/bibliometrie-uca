"""Correction des métadonnées canoniques.

Expose `effective_metadata`, fonction pure qui applique des règles de correction sur les valeurs d'une publication source, à partir de `SourcePublicationForCorrection` — sa vue d'entrée, qui porte les champs lus **plus** des champs joints depuis `journals` (`journal_type`, `oa_model`, `apc_amount`). C'est ce qui rend la fonction capable d'appliquer aussi bien les règles SP-intrinsèques (URL) que les règles journal-dépendantes, sans threader de repo.

Distincte de l'agrégation (`aggregation.py` arbitre entre sources) et du normalizer (qui ne mute pas `source_publications`, trace inviolable des sources). Les corrections s'appliquent sur le canonique via `refresh_from_sources` et sur la SP entrante au moment du matching, pour que la dédup matche sur les valeurs corrigées.

Architecture : chaque règle est une entrée du dict `_RULES`, mappant un membre de `MetadataCorrectionRule` à sa définition `{applies_to, applies_correction}` où :
- `applies_to` est un dict de prédicats AND-és sur la SP (clés typées par `_AppliesTo`).
- `applies_correction` est un dict champ → valeur cible (une seule entrée par règle aujourd'hui).

Le moteur `_check_predicate` interprète chaque clé d'`applies_to` selon une convention fixe (voir le TypedDict `_AppliesTo` pour la liste exhaustive). `_correct_field(sp, "doc_type")` parcourt les règles dans l'ordre du dict et retourne la première qui (a) corrige le champ demandé et (b) dont tous les prédicats matchent.

Cascade entre champs (ordre des dépendances) : `journal_id` → `doc_type` → `oa_status`. La provenance (le membre `MetadataCorrectionRule` ayant produit la correction) est tracée par le caller, à un emplacement propre à chaque niveau : une `source_publication` la stashe dans `raw_metadata.<champ>.corrected_by`, **avec la valeur brute écrasée** (réversibilité, la colonne est mutée en place) ; une publication canonique l'inscrit dans `meta.corrections.<champ>` (provenance seule — le canonique est recalculé à chaque refresh, sans brut à préserver).
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import combinations
from typing import NamedTuple, TypedDict

from domain.normalize import normalize_text
from domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class SourcePublicationForCorrection:
    """Vue d'une `source_publications` pour la correction de métadonnées.

    Contrat d'entrée de `effective_metadata` (et `hydrate_raw_view`) : les champs
    lus par les règles — **valeurs courantes** des colonnes (potentiellement déjà
    corrigées d'un run précédent) plus les champs joints de `journals`
    (`journal_type`, `oa_model`, `apc_amount`) — et `raw_metadata`, qui reconstruit
    le brut normalisé d'origine (`raw_metadata->'<champ>'->>'raw'` prime sur la
    colonne). Sous-ensemble dédié : l'entité `SourcePublication` complète n'est pas
    requise (la correction ne porte aucun invariant).

    Frozen : `hydrate_raw_view` et la cascade produisent une nouvelle vue via
    `dataclasses.replace`, jamais une mutation en place.
    """

    id: int
    source: str
    source_id: str
    title: str
    pub_year: int | None
    doc_type: str | None
    doi: str | None
    journal_id: int | None
    oa_status: str | None
    container_title: str | None
    language: str | None
    urls: list[str] | None
    external_ids: dict[str, JsonValue]
    journal_type: str | None
    oa_model: str | None
    apc_amount: Decimal | None
    raw_metadata: dict[str, JsonValue]
    # Calculé au fetch (`embargo_until <= current_date`), pas une colonne : seule donnée
    # date-dépendante de la vue, pour garder `effective_metadata` pure (elle lit un booléen).
    embargo_expired: bool


class MetadataCorrectionRule(StrEnum):
    """Identifiants des règles de correction figées. Une règle = un membre.

    Convention de nommage : `INPUT_CONDITION_TO_OUTPUT`. Le membre est tracé par le caller au moment où la règle est appliquée (`source_publications.raw_metadata.<champ>.corrected_by` côté SP, `publications.meta.corrections.<champ>` côté canonique) — trace d'audit consultable pour le re-run ciblé et l'affichage UI.
    """

    THESES_FR_URL_TO_THESIS = "THESES_FR_URL_TO_THESIS"
    DUMAS_URL_TO_MEMOIR = "DUMAS_URL_TO_MEMOIR"
    THESIS_WITH_JOURNAL_TO_ARTICLE = "THESIS_WITH_JOURNAL_TO_ARTICLE"
    JOURNAL_TYPE_MEDIA_TO_MEDIA = "JOURNAL_TYPE_MEDIA_TO_MEDIA"
    JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER = "JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER"
    JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT = "JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT"
    TITLE_MEDIA_PREFIX_TO_MEDIA = "TITLE_MEDIA_PREFIX_TO_MEDIA"
    TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET = "TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET"
    TITLE_ERRATUM_PREFIX_TO_ERRATUM = "TITLE_ERRATUM_PREFIX_TO_ERRATUM"
    TITLE_RETRACTION_PREFIX_TO_RETRACTION = "TITLE_RETRACTION_PREFIX_TO_RETRACTION"
    TITLE_EDITORIAL_PREFIX_TO_EDITORIAL = "TITLE_EDITORIAL_PREFIX_TO_EDITORIAL"
    TITLE_LETTER_PREFIX_TO_LETTER = "TITLE_LETTER_PREFIX_TO_LETTER"
    TITLE_SYSTEMATIC_REVIEW_TO_REVIEW = "TITLE_SYSTEMATIC_REVIEW_TO_REVIEW"
    TITLE_ISBN_TO_BOOK_REVIEW = "TITLE_ISBN_TO_BOOK_REVIEW"
    TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW = "TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW"
    DOI_FIGSHARE_COLLECTION_TO_DATASET = "DOI_FIGSHARE_COLLECTION_TO_DATASET"
    EMBARGO_EXPIRED_TO_GREEN = "EMBARGO_EXPIRED_TO_GREEN"


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
_ERRATUM_TITLE_PREFIXES = ("erratum", "errata", "corrigendum", "author correction", "publisher correction")

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

# Préfixes DOI des registres de thèses : un DOI émis par ces registres est le DOI *propre* de la
# thèse, pas celui d'une version publiée. `10.70675` = ABES (Agence Bibliographique de
# l'Enseignement Supérieur), résolu via `doi_prefixes` (publisher « agence bibliographique de l
# enseignement superieur »). Ensemble volontairement incomplet : les thèses déposées en repository
# institutionnel (Wageningen, Karlsruhe…) ont des préfixes variés non listés — elles n'apparaissent
# pas avec un journal_id aujourd'hui (conflations → relations-publications). Les généraliser suppose
# une nature de registrant (éditeur vs repository vs registre) dans `doi_prefixes`, absente à ce jour.
_THESIS_REGISTRY_DOI_PREFIXES = ("10.70675",)


# ── Mini-DSL des règles ─────────────────────────────────────────────────


class _AppliesTo(TypedDict, total=False):
    """Prédicats supportés dans la clause `applies_to` d'une règle.

    Toutes les clés présentes sont AND-ées. Les clés absentes sont ignorées (pas de prédicat sur ce champ).

    - ``doc_type`` : `str` (équivalence après lowercase) ou `frozenset[str]` (appartenance après lowercase). Whitelist : limite la règle aux types bruts plausibles, épargne les types-référents (thesis, book, …).
    - ``journal_type`` : `str` — équivalence sur `sp.journal_type` (champ joint depuis `journals`).
    - ``url_contains`` : `str` — substring présente dans au moins une des `sp.urls`.
    - ``doi_contains`` : `str` — substring présente dans `sp.doi` (DOIs stockés en minuscules).
    - ``title_prefix_normalized`` : `tuple[str, ...]` — `normalize_text(sp.title)` commence par au moins un préfixe du tuple.
    - ``title_regex`` : `re.Pattern[str]` — `pattern.search(sp.title)` matche.
    - ``journal_id_present`` : `bool` — `(sp.journal_id is not None)` vaut la valeur attendue. Signal « la SP est rattachée à un journal » (donc un article, pas une thèse).
    - ``doi_prefix_not_in`` : `tuple[str, ...]` — la SP porte un DOI **et** son préfixe (`doi.split('/')[0]`) n'appartient à aucun préfixe du tuple. Faux si pas de DOI (le prédicat affirme quelque chose *sur* le DOI). Sert à exclure des registrants connus par préfixe (ex. registres de thèses).
    - ``oa_status`` : `str` — équivalence sur `sp.oa_status` (le statut d'entrée, ex. `embargoed`).
    - ``embargo_expired`` : `bool` — `sp.embargo_expired` (calculé au fetch : `embargo_until <= current_date`) vaut la valeur attendue.

    Ajouter un nouveau type de prédicat = ajouter une clé ici + une branche dans `_check_predicate`.
    """

    doc_type: str | frozenset[str]
    journal_type: str
    url_contains: str
    doi_contains: str
    title_prefix_normalized: tuple[str, ...]
    title_regex: re.Pattern[str]
    journal_id_present: bool
    doi_prefix_not_in: tuple[str, ...]
    oa_status: str
    embargo_expired: bool


class _AppliesCorrection(TypedDict, total=False):
    """Champ corrigé et sa valeur cible. Une seule entrée par règle aujourd'hui."""

    doc_type: str
    oa_status: str
    journal_id: int


class _RuleDefinition(TypedDict):
    applies_to: _AppliesTo
    applies_correction: _AppliesCorrection


# ── Table des règles ────────────────────────────────────────────────────
# Ordre = priorité de la cascade (signaux forts d'abord : URL > journal_type > titre). Les whitelists `doc_type` sont calibrées pour être quasi disjointes entre règles d'une même famille, donc l'ordre intra-famille importe peu en pratique. La règle ISBN évaluée avant la règle année-pages : un titre porteur d'un ISBN explicite est plus fiable.

_RULES: dict[MetadataCorrectionRule, _RuleDefinition] = {
    # theses.fr fait autorité sur les thèses françaises (OpenAlex classe parfois ces thèses en `article` ou `dissertation`). Gardée par `journal_id_present: False` : une SP theses.fr AVEC un journal_id est une conflation thèse↔article publié — c'est l'aspect article qui prime (`THESIS_WITH_JOURNAL_TO_ARTICLE`), pas l'URL theses.fr. La règle ne corrige donc en `thesis` que les SP theses.fr **sans** journal.
    MetadataCorrectionRule.THESES_FR_URL_TO_THESIS: {
        "applies_to": {"url_contains": "theses.fr/", "journal_id_present": False},
        "applies_correction": {"doc_type": "thesis"},
    },
    # DUMAS (dumas.ccsd) n'héberge que des mémoires : URL-only, même garde `journal_id_present: False` que theses.fr (une SP DUMAS avec journal_id = article publié → prime sur le mémoire).
    MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR: {
        "applies_to": {"url_contains": "dumas.ccsd", "journal_id_present": False},
        "applies_correction": {"doc_type": "memoir"},
    },
    # Famille thèse + `journal_id` présent ⇒ `article`, SAUF si le DOI est celui d'un registre de
    # thèses (`doi_prefix_not_in`). Une vraie thèse a un DOI ABES (ou pas de DOI) ; un DOI d'éditeur
    # signe au contraire la version publiée. Le `doc_type=thesis` + `journal_id` + DOI éditeur est
    # donc un article publié (mistype d'OpenAlex/ScanR, ou conflation thèse↔version publiée mergées
    # par titre) → `article`. Avec un DOI ABES ou aucun DOI, le `journal_id` est parasite (la version
    # publiée d'une conflation) : le type reste thèse, le nettoyage du journal_id relève des relations.
    # Placée APRÈS les règles URL : une SP theses.fr/DUMAS reste thèse/mémoire (l'URL est le signal
    # fort). Le nullage des clés-thèse (NNT, hal_id `tel-`/`dumas-`) de la conflation est traité à
    # part (mutation `external_ids`, hors DSL colonne).
    MetadataCorrectionRule.THESIS_WITH_JOURNAL_TO_ARTICLE: {
        "applies_to": {
            "doc_type": frozenset({"thesis", "ongoing_thesis", "memoir"}),
            "journal_id_present": True,
            "doi_prefix_not_in": _THESIS_REGISTRY_DOI_PREFIXES,
        },
        "applies_correction": {"doc_type": "article"},
    },
    # Journal typé `media` (typage manuel admin) ⇒ `media` quel que soit le `doc_type` brut.
    MetadataCorrectionRule.JOURNAL_TYPE_MEDIA_TO_MEDIA: {
        "applies_to": {"journal_type": "media"},
        "applies_correction": {"doc_type": "media"},
    },
    # Journal d'actes + doc_type plausible ⇒ `conference_paper`. `book` exclu : un volume entier d'actes peut légitimement rester `book`.
    MetadataCorrectionRule.JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER: {
        "applies_to": {
            "journal_type": "proceedings",
            "doc_type": frozenset({"article", "book_chapter"}),
        },
        "applies_correction": {"doc_type": "conference_paper"},
    },
    # Serveur de preprints (arXiv, bioRxiv, ChemRxiv, EGUsphere, SSRN, …) + doc_type ∈ {article, other} ⇒ `preprint`. Whitelist étroite : les SPs CrossRef ont `journal-article`, l'arbitrage canonique efface parfois le `preprint` brut OA. `dataset`/`software`/`poster` épargnés.
    MetadataCorrectionRule.JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT: {
        "applies_to": {
            "journal_type": "preprint_server",
            "doc_type": frozenset({"article", "other"}),
        },
        "applies_correction": {"doc_type": "preprint"},
    },
    # Titre `interview`/`reportage`/`podcast` + `doc_type` ∈ {article, other} ⇒ `media`. Patterns univoques et récurrents dans le corpus UCA.
    MetadataCorrectionRule.TITLE_MEDIA_PREFIX_TO_MEDIA: {
        "applies_to": {
            "doc_type": frozenset({"article", "other"}),
            "title_prefix_normalized": _MEDIA_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": "media"},
    },
    # Collection figshare (`10.6084/m9.figshare.c.<id>` — le `.c.` marque un bundle de suppléments, vs un item `m9.figshare.<id>`) + doc_type ∈ {article, other} ⇒ `dataset`. Le titre d'une collection = le titre du papier parent, donc inattrapable par la règle titre supplément → discrimination par DOI. Fallback hardcodé ; une détection RA DataCite (figshare-as-client) généraliserait aux instances figshare sous d'autres préfixes.
    MetadataCorrectionRule.DOI_FIGSHARE_COLLECTION_TO_DATASET: {
        "applies_to": {
            "doc_type": frozenset({"article", "other"}),
            "doi_contains": "m9.figshare.c.",
        },
        "applies_correction": {"doc_type": "dataset"},
    },
    # Titre suppléments / données complémentaires + doc_type ∈ {article, other} ⇒ `dataset`. DataCite et certaines plateformes (Dryad, Zenodo, IFREMER) exposent les fichiers complémentaires comme entités à part. `dataset` lui-même exclu (no-op naturel).
    MetadataCorrectionRule.TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET: {
        "applies_to": {
            "doc_type": frozenset({"article", "other"}),
            "title_prefix_normalized": _SUPPLEMENTARY_CONTENT_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": "dataset"},
    },
    # Titre `erratum`/`errata`/`corrigendum` + doc_type publication-like ⇒ `erratum`. OpenAlex reclasse fréquemment ces corrections en `article`/`preprint`/`data_paper`. Types-référents (thesis, book, dataset, …) épargnés.
    MetadataCorrectionRule.TITLE_ERRATUM_PREFIX_TO_ERRATUM: {
        "applies_to": {
            "doc_type": frozenset(
                {
                    "article",
                    "preprint",
                    "review",
                    "conference_paper",
                    "data_paper",
                    "letter",
                    "other",
                }
            ),
            "title_prefix_normalized": _ERRATUM_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": "erratum"},
    },
    # Titre `retraction notice/note` + doc_type ∈ {article, other} ⇒ `retraction`. Préfixes stricts pour éviter un faux positif sur un article *sur* la rétractation.
    MetadataCorrectionRule.TITLE_RETRACTION_PREFIX_TO_RETRACTION: {
        "applies_to": {
            "doc_type": frozenset({"article", "other"}),
            "title_prefix_normalized": _RETRACTION_TITLE_PREFIXES,
        },
        "applies_correction": {"doc_type": "retraction"},
    },
    # Titre « Editorial: … » + doc_type ∈ {article, other} ⇒ `editorial`. Frontiers & co.
    # publient les éditoriaux sous ce préfixe, qu'OpenAlex/ScanR/CrossRef typent souvent
    # `article`. Ancré sur le « : » (cf. `_EDITORIAL_PREFIX_PATTERN`).
    MetadataCorrectionRule.TITLE_EDITORIAL_PREFIX_TO_EDITORIAL: {
        "applies_to": {
            "doc_type": frozenset({"article", "other"}),
            "title_regex": _EDITORIAL_PREFIX_PATTERN,
        },
        "applies_correction": {"doc_type": "editorial"},
    },
    # Titre « Letter: … » + doc_type ∈ {article, other} ⇒ `letter`. Courriers à l'éditeur /
    # research letters mal typés `article`.
    MetadataCorrectionRule.TITLE_LETTER_PREFIX_TO_LETTER: {
        "applies_to": {
            "doc_type": frozenset({"article", "other"}),
            "title_regex": _LETTER_PREFIX_PATTERN,
        },
        "applies_correction": {"doc_type": "letter"},
    },
    # « systematic review » en tête ou en sous-titre + doc_type ∈ {article, other} ⇒ `review`.
    # Ancré (cf. `_SYSTEMATIC_REVIEW_PATTERN`) pour ne prendre que la forme document-type, pas
    # les mentions au fil du titre. La whitelist épargne conference_paper/preprint/poster/
    # memoir/dataset (une revue systématique peut légitimement être l'un d'eux).
    MetadataCorrectionRule.TITLE_SYSTEMATIC_REVIEW_TO_REVIEW: {
        "applies_to": {
            "doc_type": frozenset({"article", "other"}),
            "title_regex": _SYSTEMATIC_REVIEW_PATTERN,
        },
        "applies_correction": {"doc_type": "review"},
    },
    # Titre porteur d'un ISBN explicite + doc_type ∈ {article, review, other} ⇒ `book_review`. `book`/`book_chapter` exclus (un ouvrage ou un chapitre peut légitimement porter son propre ISBN dans le titre — saisie HAL fréquente).
    MetadataCorrectionRule.TITLE_ISBN_TO_BOOK_REVIEW: {
        "applies_to": {
            "doc_type": frozenset({"article", "review", "other"}),
            "title_regex": _ISBN_PATTERN,
        },
        "applies_correction": {"doc_type": "book_review"},
    },
    # Titre terminé par « (19|20)YY, N p[.|ages] » + même whitelist que la règle ISBN ⇒ `book_review`. Plus bruité que ISBN, évaluée après.
    MetadataCorrectionRule.TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW: {
        "applies_to": {
            "doc_type": frozenset({"article", "review", "other"}),
            "title_regex": _YEAR_PAGES_END_PATTERN,
        },
        "applies_correction": {"doc_type": "book_review"},
    },
    # Embargo HAL levé : un dépôt typé `embargoed` dont la date de fin est passée
    # (`embargo_expired`, calculé au fetch) devient `green`. Promotion à l'échéance sans
    # ré-import HAL — seule règle date-dépendante (la date vit dans le fetch, pas dans la
    # fonction pure). Trace dans `raw_metadata.oa_status` ; corrige un champ orthogonal au
    # `doc_type`, donc aucun chaînage avec les règles ci-dessus.
    MetadataCorrectionRule.EMBARGO_EXPIRED_TO_GREEN: {
        "applies_to": {"oa_status": "embargoed", "embargo_expired": True},
        "applies_correction": {"oa_status": "green"},
    },
}


# ── Moteur ──────────────────────────────────────────────────────────────


def _check_predicate(sp: SourcePublicationForCorrection, key: str, value: object) -> bool:
    """Évalue un prédicat (paire clé/valeur de `applies_to`) sur la SP. Voir `_AppliesTo` pour la sémantique de chaque clé."""
    if key == "doc_type":
        doc_type = (sp.doc_type or "").lower()
        if isinstance(value, frozenset):
            return doc_type in value
        return doc_type == value
    if key == "journal_type":
        return sp.journal_type == value
    if key == "url_contains":
        assert isinstance(value, str)
        return any(value in (u or "") for u in (sp.urls or ()))
    if key == "doi_contains":
        assert isinstance(value, str)
        return value in (sp.doi or "")
    if key == "title_prefix_normalized":
        assert isinstance(value, tuple)
        if not sp.title:
            return False
        normalized = normalize_text(sp.title)
        return any(normalized.startswith(p) for p in value)
    if key == "title_regex":
        assert isinstance(value, re.Pattern)
        return bool(sp.title and value.search(sp.title))
    if key == "journal_id_present":
        assert isinstance(value, bool)
        return (sp.journal_id is not None) == value
    if key == "doi_prefix_not_in":
        assert isinstance(value, tuple)
        if not sp.doi:
            return False
        return sp.doi.split("/", 1)[0] not in value
    if key == "oa_status":
        return sp.oa_status == value
    if key == "embargo_expired":
        assert isinstance(value, bool)
        return sp.embargo_expired == value
    raise ValueError(f"Prédicat inconnu : {key!r}")


def _rule_applies(sp: SourcePublicationForCorrection, rule_def: _RuleDefinition) -> bool:
    """True si tous les prédicats `applies_to` de la règle sont vérifiés (AND)."""
    return all(_check_predicate(sp, k, v) for k, v in rule_def["applies_to"].items())


def _correct_field(sp: SourcePublicationForCorrection, field: str) -> Correction[str] | None:
    """Applique les règles `_RULES` dans l'ordre ; première qui corrige `field` et dont les prédicats matchent gagne."""
    for rule_id, rule_def in _RULES.items():
        if field not in rule_def["applies_correction"]:
            continue
        if _rule_applies(sp, rule_def):
            return Correction(rule_def["applies_correction"][field], rule_id)  # type: ignore[literal-required]
    return None


# TODO: corrections indépendantes par champ — pas de feed-forward d'un champ corrigé vers les
# règles des champs suivants. Une vraie cascade (journal_id → doc_type → oa_status alimentés au
# fil de l'eau) serait plus logique et pourrait changer le résultat quand des règles se croisent.
# Hors scope tant qu'aucune règle ne dépend d'un autre champ déjà corrigé.
def effective_metadata(sp: SourcePublicationForCorrection) -> CorrectedFields:
    """Applique la cascade de corrections sur les champs d'une `SourcePublicationForCorrection`. Retourne un `CorrectedFields` (vide si aucune règle ne s'applique).

    Fonction pure : aucune I/O, aucun effet de bord. Les données journal/publisher consommées par les règles arrivent par la vue (champs joints à la lecture), pas via des entités passées en paramètre — c'est ce qui permet à la fonction de servir aussi bien la dédup (sur la SP entrante) que le refresh (sur les sources d'une publication).

    Cascade dans l'ordre des dépendances (`journal_id` → `doc_type` → `oa_status`). Chaque champ est corrigé **indépendamment** depuis la même vue d'entrée (pas de feed-forward d'un champ corrigé vers un autre) ; `doc_type` et `oa_status` (promotion d'embargo) portent des règles.
    """
    return CorrectedFields(
        doc_type=_correct_field(sp, "doc_type"),
        oa_status=_correct_field(sp, "oa_status"),
    )


# Préfixes d'identifiants HAL propres aux dissertations : TEL (thèses en ligne) et DUMAS
# (mémoires/dissertations étudiantes). Un hal_id à ce préfixe n'est jamais celui d'un article.
_DISSERTATION_HALID_PREFIXES = ("tel-", "dumas-")


def strip_dissertation_keys(external_ids: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Retire d'un `external_ids` les clés propres aux **dissertations**, erronées sur une SP
    article (conflation thèse↔article publié : OpenAlex/ScanR fusionnent une thèse et son article
    dans un seul enregistrement, en gardant le `nnt` / les hal_id `tel-`/`dumas-` de la thèse).

    Retire `nnt` et les `hal_id` préfixés `tel-`/`dumas-` (en conservant les autres hal_id, qui
    pointent l'article). Pur. Le caller n'appelle cette fonction que sur les SP corrigées
    thèse→article (`THESIS_WITH_JOURNAL_TO_ARTICLE`)."""
    result = {k: v for k, v in external_ids.items() if k != "nnt"}
    hal_ids = result.get("hal_id")
    if isinstance(hal_ids, list):
        kept = [
            h
            for h in hal_ids
            if not (isinstance(h, str) and h.startswith(_DISSERTATION_HALID_PREFIXES))
        ]
        if kept:
            result["hal_id"] = kept
        else:
            result.pop("hal_id", None)
    return result


# ── Corrections relationnelles : conflits de clé partagée ────────────────
#
# Les corrections unaires ci-dessus décident d'un record seul. Certaines corrections
# demandent au contraire de regarder le **groupe de source_publications partageant une
# clé** (DOI, hal_id, nnt, … ; à terme une clé de métadonnées) : quand ce groupe réunit
# des œuvres en réalité distinctes, la clé partagée est erronée et doit être nullée sur le
# ou les mauvais côtés — sinon le matching les fusionnerait à tort. La détection est
# **agnostique de la clé** (elle raisonne sur les `doc_type` du groupe) ; le caller
# applicatif regroupe par une clé donnée et persiste le nullage de CETTE clé.


class DistinctMergeCase(StrEnum):
    """Cas où des SP partageant une clé sont en réalité des œuvres distinctes. Inscrit dans
    `raw_metadata.<clé>.corrected_by` au nullage."""

    # Ouvrage et chapitre partageant une clé : la clé appartient à l'ouvrage (`book`), le
    # chapitre (`book_chapter`) la porte par erreur → le chapitre la perd.
    OUVRAGE_VS_CHAPITRE = "OUVRAGE_VS_CHAPITRE"

    # Plusieurs chapitres (`book_chapter`) partageant une clé mais de titres réellement
    # différents : la clé est celle de l'ouvrage hôte (absent du groupe), recopiée à tort sur
    # ses chapitres → tous la perdent.
    CHAPITRES_TITRES_DIFFERENTS = "CHAPITRES_TITRES_DIFFERENTS"


class KeyGroupMember(NamedTuple):
    """Un membre d'un groupe de SP partageant une clé : son id, son `doc_type` **canonique**
    (corrigé par la passe unaire) et son `title_normalized` (matérialisé)."""

    id: int
    doc_type: str | None
    title_normalized: str | None


# Marqueurs structurels de titre de chapitre, retirés avant comparaison : un chapitre est
# fréquemment saisi avec son numéro (« chapitre 14 … ») par une source et sans par une autre.
_CHAPTER_TITLE_MARKERS = re.compile(
    r"\b(chapitre|chapter|chap|ch|section|sec|partie|part|vol|tome|pp|p)\b"
)


def _clean_chapter_title(title_normalized: str | None) -> str:
    """Retire le bruit structurel d'un titre normalisé (chiffres = numéros de chapitre/page,
    mots-marqueurs) et re-collapse les espaces, pour comparer des **chapitres** sans qu'un
    numéro ou un marqueur fasse paraître distincts deux enregistrements du même chapitre.
    Déterministe (aucune similarité floue)."""
    cleaned = re.sub(r"\d+", " ", title_normalized or "")
    cleaned = _CHAPTER_TITLE_MARKERS.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _group_has_distinct_chapters(titles: list[str | None]) -> bool:
    """True si le groupe contient deux chapitres **réellement distincts** : après nettoyage,
    une paire de titres qui ne sont ni égaux ni l'un contenu dans l'autre (la containment
    couvre les troncatures de sous-titre). Identité stricte sur le résidu — pas de seuil flou."""
    cleaned = [c for c in (_clean_chapter_title(t) for t in titles) if c]
    return any(a != b and a not in b and b not in a for a, b in combinations(cleaned, 2))


def detect_erroneous_key_holders(
    group: list[KeyGroupMember],
) -> list[tuple[int, DistinctMergeCase]]:
    """Pour un groupe de SP partageant une clé (quelle qu'elle soit), renvoie les `(sp_id, cas)`
    qui la portent **par erreur** (à nuller). Pur, déterministe, sans effet de bord, et
    indépendant du type de clé — c'est le caller qui sait par quelle clé le groupe est formé.

    - **Ouvrage + chapitre** dans le groupe : les `book_chapter` perdent la clé (celle de
      l'ouvrage). Signal = le mix de `doc_type`, sans comparaison de titre.
    - **Chapitres seuls, titres réellement différents** : tous les `book_chapter` perdent la
      clé (celle de l'ouvrage hôte absent). Détection par nettoyage + containment + identité
      stricte (`_group_has_distinct_chapters`) — pas de similarité floue. Les faux positifs
      résiduels (coquilles) relèvent d'une correction admin.

    Différé : thèse/article (souvent un mistype → correction de `doc_type`, pas un nullage)."""
    types = {m.doc_type for m in group}
    if "book" in types and "book_chapter" in types:
        return [
            (m.id, DistinctMergeCase.OUVRAGE_VS_CHAPITRE)
            for m in group
            if m.doc_type == "book_chapter"
        ]
    if types == {"book_chapter"} and _group_has_distinct_chapters(
        [m.title_normalized for m in group]
    ):
        return [(m.id, DistinctMergeCase.CHAPITRES_TITRES_DIFFERENTS) for m in group]
    return []
