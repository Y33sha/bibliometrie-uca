"""Correction des métadonnées canoniques.

Expose `effective_metadata`, fonction pure qui applique des règles de correction sur les valeurs d'une publication source, à partir d'une vue de lecture `SourcePublicationWithJournalView` qui porte les champs de la SP **plus** des champs joints depuis `journals` (`journal_type`, `oa_model`, `apc_amount`). C'est cette vue qui rend la fonction capable d'appliquer aussi bien les règles SP-intrinsèques (URL) que les règles journal-dépendantes, sans threader de repo.

Distincte de l'agrégation (`aggregation.py` arbitre entre sources) et du normalizer (qui ne mute pas `source_publications`, trace inviolable des sources). Les corrections s'appliquent sur le canonique via `refresh_from_sources` et sur la SP entrante au moment du matching, pour que la dédup matche sur les valeurs corrigées.

Cascade déterministe, dans l'ordre des dépendances entre champs : `journal_id` (une correction du journal devient l'input des règles suivantes), puis `doc_type`, puis `oa_status`.

Chaque règle est une fonction pure renvoyant `Correction | None` : la valeur corrigée et le membre de `MetadataCorrectionRule` qui l'a produite. Le caller inscrit ce membre dans `publications.meta.<field>_corrected_by` pour tracer la correction.
"""

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
    TITLE_MEDIA_PREFIX_TO_MEDIA = "TITLE_MEDIA_PREFIX_TO_MEDIA"
    TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET = "TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET"
    TITLE_ERRATUM_PREFIX_TO_ERRATUM = "TITLE_ERRATUM_PREFIX_TO_ERRATUM"
    TITLE_RETRACTION_PREFIX_TO_RETRACTION = "TITLE_RETRACTION_PREFIX_TO_RETRACTION"


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


# ── Règles individuelles ───────────────────────────────────────────

_THESES_FR_URL_MARKER = "theses.fr/"
_DUMAS_URL_MARKER = "dumas."

# Whitelist des `doc_type` bruts que la règle `JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER` reclasse. Restreinte à `{article, book_chapter}` par prudence : ce sont les classifications par défaut que les normalizers donnent aux papiers de conférence quand l'éditeur du journal d'actes est classique. `book` est exclu : un volume entier d'actes peut légitimement rester `book`.
_PROCEEDINGS_JOURNAL_APPLIES_TO = frozenset({"article", "book_chapter"})

# Préfixes (post-`normalize_text`) reconnus comme « contenu supplémentaire / données complémentaires ». Set ciblé plutôt que `'supplementary '` large pour éviter de matcher par accident un vrai article du type "Supplementary roles of X" — aucun cas en base aujourd'hui, mais on garde la marge.
_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES = (
    "additional file",
    "supplementary material",
    "supplementary data",
    "supplementary information",
    "supplementary file",  # couvre "file" et "files"
    "supplementary dataset",  # couvre "dataset" et "datasets"
    "data from",
)

# Whitelist des `doc_type` bruts que la règle `TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET` reclasse en `dataset`. Les autres types restent inchangés (ni `thesis` ni `book_chapter` etc. ne sont concernés — un titre de supplément sur un de ces types serait suspect mais on ne corrige pas aveuglément). `dataset` lui-même est exclu du set : la règle n'a rien à faire sur une publication déjà classée `dataset`.
_SUPPLEMENTARY_CONTENT_APPLIES_TO = frozenset({"article", "other"})

# Préfixes (post-`normalize_text`) reconnus comme intervention média. Patterns récurrents : "Interview …", "Podcast Émission radio …", "Reportage pour …".
_MEDIA_TITLE_PREFIXES = ("interview", "reportage", "podcast")

# Whitelist des `doc_type` bruts que la règle `TITLE_MEDIA_PREFIX_TO_MEDIA` reclasse en `media`. Set étroit `{article, other}` : ce sont les classifications par défaut que les normalizers OpenAlex/HAL appliquent aux dépôts médias mal typés. Les types-référents (thesis, book, etc.) sont épargnés. `media` lui-même est exclu (no-op naturel) ; les cas couverts par `JOURNAL_TYPE_MEDIA_TO_MEDIA` (journal typé media) sont déjà attrapés en amont dans la cascade.
_MEDIA_TITLE_APPLIES_TO = frozenset({"article", "other"})

# Préfixes (post-`normalize_text`) reconnus comme erratum. Pattern textuel très spécifique (mot exact en tête de titre, après normalisation), univoque dans les corpus observés.
_ERRATUM_TITLE_PREFIXES = ("erratum", "errata", "corrigendum")

# Whitelist des `doc_type` bruts que la règle `TITLE_ERRATUM_PREFIX_TO_ERRATUM` reclasse en `erratum`. Restreinte aux types publication-like où un erratum est plausible (article, preprint, review, conference_paper, data_paper, letter, other). Les types-référents (thesis, book, book_chapter, memoir, hdr, dataset, …) sont épargnés : un titre erratum sur l'un d'eux serait suspect mais on ne corrige pas aveuglément. `erratum` lui-même est exclu (no-op naturel).
_ERRATUM_APPLIES_TO = frozenset(
    {"article", "preprint", "review", "conference_paper", "data_paper", "letter", "other"}
)

# Préfixes (post-`normalize_text`) reconnus comme avis de rétractation. Stricts : seuls « Retraction notice » et « Retraction note » (les formulations canoniques utilisées par les éditeurs). Pas « retraction » seul, qui matcherait par accident des titres comme « Retraction of consent in clinical trials ».
_RETRACTION_TITLE_PREFIXES = ("retraction notice", "retraction note")

# Whitelist `{article, other}` : seuls types où les normalizers (HAL/OpenAlex) classent à tort un avis de rétractation. Pattern aligné sur les règles `TITLE_*` SP-intrinsèques précédentes.
_RETRACTION_APPLIES_TO = frozenset({"article", "other"})


def _correct_doc_type(sp: SourcePublicationWithJournalView) -> Correction[str] | None:
    """Corrige le `doc_type` selon une cascade prioritaire.

    Ordre :
    1. theses.fr fait autorité sur les thèses françaises : toute URL theses.fr ⇒ `thesis`, quel que soit le `doc_type` brut (OpenAlex classe parfois ces thèses en `article` ou `dissertation`).
    2. DUMAS héberge des mémoires de master qu'OpenAlex classe à tort en `dissertation` : `dissertation` brut + URL dumas ⇒ `memoir`.
    3. Journal de type `media` ⇒ `media` : une publication rattachée à une revue typée media (typage manuel côté admin) est une intervention média.
    4. Journal de type `proceedings` + `doc_type` dans `_PROCEEDINGS_JOURNAL_APPLIES_TO` ⇒ `conference_paper` : une publication dans un journal d'actes classée à tort `article` ou `book_chapter` par les sources. `book` est exclu (un volume entier d'actes peut légitimement rester `book`).
    5. Titre commençant par `interview` / `reportage` / `podcast` + `doc_type` dans `_MEDIA_TITLE_APPLIES_TO` ⇒ `media` : les dépôts d'interventions média (radio, podcast, TV) sont fréquemment classés `other` par HAL ou `article` par OpenAlex. Pattern de titre univoque et récurrent dans le corpus UCA.
    6. Titre commençant par un préfixe de `_SUPPLEMENTARY_CONTENT_TITLE_PREFIXES` (additional file, supplementary material/data/info/file/dataset, data from) + `doc_type` dans `_SUPPLEMENTARY_CONTENT_APPLIES_TO` ⇒ `dataset` : DataCite et certaines plateformes (Dryad, Zenodo, IFREMER) exposent les fichiers complémentaires comme des entités à part entière, classées `article` (faux) ou `other` (vague) par les normalizers. Une publication déjà classée `dataset` est laissée telle quelle (classification correcte).
    7. Titre commençant par `erratum` / `errata` / `corrigendum` + `doc_type` dans `_ERRATUM_APPLIES_TO` ⇒ `erratum` : les sources (notamment OpenAlex) reclassent fréquemment les corrections en `article`/`preprint`/`data_paper`. Pattern textuel univoque (mot exact en tête de titre).
    8. Titre commençant par `retraction notice` / `retraction note` + `doc_type` dans `_RETRACTION_APPLIES_TO` ⇒ `retraction` : préfixes stricts pour éviter un faux positif sur un article *sur* la rétractation (« Retraction of consent in clinical trials »).

    Les règles 1, 2, 5, 6, 7 et 8 sont SP-intrinsèques (lisent `sp.urls`/`sp.title`/`sp.doc_type`) ; 3 et 4 sont journal-dépendantes (lisent `sp.journal_type`, champ joint sur la vue). Renvoie `None` si aucune ne s'applique.
    """
    urls = sp.urls
    if any(_THESES_FR_URL_MARKER in (u or "") for u in urls):
        return Correction("thesis", MetadataCorrectionRule.THESES_FR_URL_TO_THESIS)
    if (sp.doc_type or "").lower() == "dissertation" and any(
        _DUMAS_URL_MARKER in (u or "") for u in urls
    ):
        return Correction("memoir", MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR)
    if sp.journal_type == "media":
        return Correction("media", MetadataCorrectionRule.JOURNAL_TYPE_MEDIA_TO_MEDIA)
    if sp.journal_type == "proceedings" and sp.doc_type in _PROCEEDINGS_JOURNAL_APPLIES_TO:
        return Correction(
            "conference_paper",
            MetadataCorrectionRule.JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER,
        )
    if sp.doc_type in _MEDIA_TITLE_APPLIES_TO:
        normalized_title = normalize_text(sp.title)
        if any(normalized_title.startswith(p) for p in _MEDIA_TITLE_PREFIXES):
            return Correction("media", MetadataCorrectionRule.TITLE_MEDIA_PREFIX_TO_MEDIA)
    if sp.doc_type in _SUPPLEMENTARY_CONTENT_APPLIES_TO:
        normalized_title = normalize_text(sp.title)
        if any(normalized_title.startswith(p) for p in _SUPPLEMENTARY_CONTENT_TITLE_PREFIXES):
            return Correction(
                "dataset", MetadataCorrectionRule.TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET
            )
    if sp.doc_type in _ERRATUM_APPLIES_TO:
        normalized_title = normalize_text(sp.title)
        if any(normalized_title.startswith(p) for p in _ERRATUM_TITLE_PREFIXES):
            return Correction("erratum", MetadataCorrectionRule.TITLE_ERRATUM_PREFIX_TO_ERRATUM)
    if sp.doc_type in _RETRACTION_APPLIES_TO:
        normalized_title = normalize_text(sp.title)
        if any(normalized_title.startswith(p) for p in _RETRACTION_TITLE_PREFIXES):
            return Correction(
                "retraction", MetadataCorrectionRule.TITLE_RETRACTION_PREFIX_TO_RETRACTION
            )
    return None


def effective_metadata(sp: SourcePublicationWithJournalView) -> CorrectedFields:
    """Applique la cascade de corrections sur les champs d'une `SourcePublicationWithJournalView`. Retourne un `CorrectedFields` (vide si aucune règle ne s'applique).

    Fonction pure : aucune I/O, aucun effet de bord. Les données journal/publisher consommées par les règles arrivent par la vue (champs joints à la lecture), pas via des entités passées en paramètre — c'est ce qui permet à la fonction de servir aussi bien la dédup (sur la SP entrante) que le refresh (sur les sources d'une publication).

    Cascade dans l'ordre des dépendances (`journal_id` → `doc_type` → `oa_status`) ; seul `doc_type` porte des règles à ce stade.
    """
    return CorrectedFields(doc_type=_correct_doc_type(sp))
