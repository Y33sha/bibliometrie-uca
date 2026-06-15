"""Correction des métadonnées canoniques.

Expose `effective_metadata`, fonction pure qui applique des règles de correction sur les valeurs d'une publication source, à partir d'une vue de lecture `SourcePublicationWithJournalView` qui porte les champs de la SP **plus** des champs joints depuis `journals` (`journal_type`, `oa_model`, `apc_amount`). C'est cette vue qui rend la fonction capable d'appliquer aussi bien les règles SP-intrinsèques (URL) que les règles journal-dépendantes, sans threader de repo.

Distincte de l'agrégation (`aggregation.py` arbitre entre sources) et du normalizer (qui ne mute pas `source_publications`, trace inviolable des sources). Les corrections s'appliquent sur le canonique via `refresh_from_sources` et sur la SP entrante au moment du matching, pour que la dédup matche sur les valeurs corrigées.

Architecture : chaque règle est une entrée du dict `_RULES`, mappant un membre de `MetadataCorrectionRule` à sa définition `{applies_to, applies_correction}` où :
- `applies_to` est un dict de prédicats AND-és sur la SP (clés typées par `_AppliesTo`).
- `applies_correction` est un dict champ → valeur cible (une seule entrée par règle aujourd'hui).

Le moteur `_check_predicate` interprète chaque clé d'`applies_to` selon une convention fixe (voir le TypedDict `_AppliesTo` pour la liste exhaustive). `_correct_field(sp, "doc_type")` parcourt les règles dans l'ordre du dict et retourne la première qui (a) corrige le champ demandé et (b) dont tous les prédicats matchent.

Cascade entre champs (ordre des dépendances) : `journal_id` → `doc_type` → `oa_status`. Le membre `MetadataCorrectionRule` qui a produit la correction est inscrit dans `publications.meta.<field>_corrected_by` par le caller, pour tracer la correction.
"""

import re
from enum import StrEnum
from itertools import combinations
from typing import NamedTuple, TypedDict

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
    DOI_FIGSHARE_COLLECTION_TO_DATASET = "DOI_FIGSHARE_COLLECTION_TO_DATASET"


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
_ERRATUM_TITLE_PREFIXES = ("erratum", "errata", "corrigendum")

# Préfixes stricts : seules les formulations canoniques utilisées par les éditeurs. Pas « retraction » seul, qui matcherait des titres comme « Retraction of consent in clinical trials ».
_RETRACTION_TITLE_PREFIXES = ("retraction notice", "retraction note")

# Marqueurs de recension d'ouvrage détectés sur le titre brut.
# `_ISBN_PATTERN` : mention « ISBN » (mot entier) ou préfixe ISBN-13 (97[89] suivi de 10–17 caractères chiffres/espaces/tirets). Signal très net.
_ISBN_PATTERN = re.compile(r"\bisbn\b|\b97[89][-\s0-9]{10,17}\b", re.IGNORECASE)
# `_YEAR_PAGES_END_PATTERN` : titre terminé par « (19|20)YY, N p[.|ages] », forme classique d'une référence biblio injectée dans le champ titre par les saisisseurs HAL pour les comptes-rendus d'ouvrage. Plus bruité que ISBN.
_YEAR_PAGES_END_PATTERN = re.compile(
    r"(19|20)\d{2}[\s,.]+\d{1,4}\s*(pp|pages?|p)\.?\s*$", re.IGNORECASE
)


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

    Ajouter un nouveau type de prédicat = ajouter une clé ici + une branche dans `_check_predicate`.
    """

    doc_type: str | frozenset[str]
    journal_type: str
    url_contains: str
    doi_contains: str
    title_prefix_normalized: tuple[str, ...]
    title_regex: re.Pattern[str]


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
    # theses.fr fait autorité sur les thèses françaises (OpenAlex classe parfois ces thèses en `article` ou `dissertation`). Inconditionnel sur le `doc_type` brut.
    MetadataCorrectionRule.THESES_FR_URL_TO_THESIS: {
        "applies_to": {"url_contains": "theses.fr/"},
        "applies_correction": {"doc_type": "thesis"},
    },
    # DUMAS (dumas.ccsd) n'héberge que des mémoires : règle URL-only, inconditionnelle sur le `doc_type` brut (comme theses.fr). La whitelist `dissertation` d'avant gardait contre les entités mêlant une thèse DUMAS et l'article publié (OpenAlex typait alors « article ») ; cette fusion abusive est désormais scindée en amont (création⇒fusion + `distinct_publications`, cas `THESE_VS_ARTICLE`), donc la règle dure peut s'appliquer. La distinction mémoire / thèse d'exercice (que DUMAS ne fait pas) est différée : « memoir » pour tout DUMAS.
    MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR: {
        "applies_to": {"url_contains": "dumas.ccsd"},
        "applies_correction": {"doc_type": "memoir"},
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
}


# ── Moteur ──────────────────────────────────────────────────────────────


def _check_predicate(sp: SourcePublicationWithJournalView, key: str, value: object) -> bool:
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
        return any(value in (u or "") for u in sp.urls)
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
    raise ValueError(f"Prédicat inconnu : {key!r}")


def _rule_applies(sp: SourcePublicationWithJournalView, rule_def: _RuleDefinition) -> bool:
    """True si tous les prédicats `applies_to` de la règle sont vérifiés (AND)."""
    return all(_check_predicate(sp, k, v) for k, v in rule_def["applies_to"].items())


def _correct_field(sp: SourcePublicationWithJournalView, field: str) -> Correction[str] | None:
    """Applique les règles `_RULES` dans l'ordre ; première qui corrige `field` et dont les prédicats matchent gagne."""
    for rule_id, rule_def in _RULES.items():
        if field not in rule_def["applies_correction"]:
            continue
        if _rule_applies(sp, rule_def):
            return Correction(rule_def["applies_correction"][field], rule_id)  # type: ignore[literal-required]
    return None


def effective_metadata(sp: SourcePublicationWithJournalView) -> CorrectedFields:
    """Applique la cascade de corrections sur les champs d'une `SourcePublicationWithJournalView`. Retourne un `CorrectedFields` (vide si aucune règle ne s'applique).

    Fonction pure : aucune I/O, aucun effet de bord. Les données journal/publisher consommées par les règles arrivent par la vue (champs joints à la lecture), pas via des entités passées en paramètre — c'est ce qui permet à la fonction de servir aussi bien la dédup (sur la SP entrante) que le refresh (sur les sources d'une publication).

    Cascade dans l'ordre des dépendances (`journal_id` → `doc_type` → `oa_status`) ; seul `doc_type` porte des règles à ce stade.
    """
    return CorrectedFields(doc_type=_correct_field(sp, "doc_type"))


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
