"""Concept métier Publication — value objects, règles, types de
résultats de recherche et (à terme) entités.

Regroupe ici tout ce qui est propre à une publication : identifiants
(DOI, HAL ID document, NNT), règles métier (résolution de conflit DOI,
agrégation OA, canonicalisation des titres), types de résultats
renvoyés par les repositories, puis plus tard les entités
`Publication`, les règles de déduplication, les invariants.

Les value objects sont immuables et auto-validés :
- construction stricte : `DOI("...")` lève ValidationError si invalide
- construction tolérante : `DOI.try_parse("...")` renvoie None quand
  l'absence est un cas normal (code pipeline qui tolère les données
  manquantes)
- la valeur stockée est toujours normalisée (canonique) : deux VO
  égaux par valeur, quel que soit le format d'entrée

Les modèles des colonnes JSONB (`external_ids`, `biblio`, `meta`,
`topics`) vivent côté infrastructure
(`infrastructure/db/jsonb_models/publication.py`) — c'est un détail
d'adapter de persistance, pas du métier.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from domain.errors import ValidationError

# ── Types de résultats de recherche ────────────────────────────────
# Utilisés par le port PublicationRepository et ses implémentations.
# Vivent dans le domaine car ils décrivent la forme d'un résultat
# métier, pas un détail d'infrastructure.
#
# Dataclasses avec `slots=True` pour occuper le mappage fait par
# `psycopg.rows.class_row(...)` : les noms de champs correspondent aux
# colonnes SELECT du repo.


@dataclass(frozen=True, slots=True)
class PubByDoi:
    id: int
    doc_type: str | None
    title_normalized: str | None


@dataclass(frozen=True, slots=True)
class PubByNnt:
    id: int
    doc_type: str | None
    title_normalized: str | None


@dataclass(frozen=True, slots=True)
class PubByTitle:
    id: int
    doi: str | None


@dataclass(frozen=True, slots=True)
class PubThesisCandidate:
    id: int
    doi: str | None


# ── DOI ────────────────────────────────────────────────────────────

# Suffixe de version sur les DOI de dépôts de données (figshare, zenodo,
# techrxiv, opticaopen…). On normalise vers le DOI "concept" (sans version)
# qui pointe toujours vers la dernière version.
_DOI_VERSION_SUFFIX = re.compile(r"\.v\d+$", re.IGNORECASE)
_DOI_URL_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/")


def _normalize_doi(raw: str | None) -> str | None:
    """Normalise un DOI brut (préfixe URL, espaces, suffixe de version, casse).

    Lowercase systématique : la spec DOI Handbook précise que le préfixe
    `10.xxxx` est insensible à la casse, et CrossRef (registre officiel)
    traite l'ensemble du DOI en case-insensitive. Stocker tout en minuscules
    évite les faux doublons lors des comparaisons cross-sources.

    Séparée de la classe pour rester appelable depuis utils/doi.py
    (compat avec les ~50 sites d'appel existants).
    """
    if not raw:
        return None
    s = raw.strip().lower()
    for prefix in _DOI_URL_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    s = s.strip()
    if not s:
        return None
    s = _DOI_VERSION_SUFFIX.sub("", s)
    return s or None


@dataclass(frozen=True)
class DOI:
    """Digital Object Identifier, normalisé et validé.

    Lève ValidationError à la construction si la valeur est invalide ou vide.
    Utiliser `DOI.try_parse()` quand l'absence est un cas normal.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_doi(self.value)
        if not cleaned:
            raise ValidationError(f"DOI invalide : {self.value!r}")
        # frozen=True interdit l'assignation directe — détour par object.__setattr__
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "DOI | None":
        """Tente de parser ; renvoie None si l'entrée est vide ou invalide."""
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── HAL ID (document) ──────────────────────────────────────────────

# Préfixes de portails HAL (liste historique, cf. utils/hal.py)
_HAL_DOC_PREFIXES = ("hal", "tel", "halshs", "inserm", "pasteur", "cea", "ineris")
_HAL_DOC_BASE = re.compile(rf"((?:{'|'.join(_HAL_DOC_PREFIXES)})-\d+)", re.IGNORECASE)


def _normalize_hal_id(raw: str | None) -> str | None:
    """Extrait le HAL ID canonique d'une chaîne ou URL.

    Accepte une URL (hal.science, tel.archives-ouvertes.fr, …) ou un HAL
    ID brut avec éventuel suffixe de version (v1, v2). Retourne l'ID
    sans version (concept HAL).
    """
    if not raw:
        return None
    s = raw.strip().lower()
    m = _HAL_DOC_BASE.search(s)
    return m.group(1) if m else None


@dataclass(frozen=True)
class HALId:
    """Identifiant HAL d'un document (hal-XXXXX, tel-XXXXX, halshs-XXXXX, …).

    Normalisé en minuscules sans suffixe de version (`hal-04123456v2` →
    `hal-04123456`). Accepte une URL en entrée.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_hal_id(self.value)
        if not cleaned:
            raise ValidationError(f"HAL ID invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "HALId | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── NNT (Numéro National de Thèse) ─────────────────────────────────


def _normalize_nnt(raw: str | None) -> str | None:
    """Normalise un NNT : uppercase + strip. Format historiquement variable,
    on se contente d'exiger une valeur alphanumérique non vide."""
    if not raw:
        return None
    s = raw.strip().upper()
    if not s or not s.isalnum():
        return None
    return s


@dataclass(frozen=True)
class NNT:
    """Numéro National de Thèse. Format typique : YYYY + code établissement
    + séquence (ex. 2021CLFAC030), mais le format a varié historiquement.

    On normalise en majuscules, trim, et on exige une valeur alphanumérique.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_nnt(self.value)
        if not cleaned:
            raise ValidationError(f"NNT invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "NNT | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── Helpers publics (API string-in/string-out) ─────────────────────
#
# Ces fonctions couvrent le besoin du code existant qui travaille sur
# des chaînes brutes (pipelines d'extraction, normalisation). Elles
# sont l'équivalent fonctionnel des VO mais en retour string|None.
# Pour un accès structuré et typé, préférer DOI/NNT/HALId directement.


def clean_doi(doi: str | None) -> str | None:
    """Nettoie un DOI brut : préfixe URL, espaces, suffixe de version.
    Retourne le DOI canonique, ou None si l'entrée est vide/inutilisable.
    """
    return _normalize_doi(doi)


def normalize_nnt(nnt: str | None) -> str | None:
    """Normalise un NNT : uppercase, strip whitespace. Retourne None
    si l'entrée est vide ou ne contient pas de caractères alphanumériques."""
    return _normalize_nnt(nnt)


# ── Décodage des titres double-encodés HTML ────────────────────────
#
# OpenAlex et ScanR remontent parfois des titres avec un encodage HTML
# appliqué deux fois — par exemple "<i>Candida</i>" arrive en base sous
# la forme "&amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt;". On corrige au
# moment d'écrire dans `publications.title` pour que la couche canonique
# reste propre, indépendamment de la qualité du flux source.

_HTML_ENTITY_NAMED = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_HTML_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
_DOUBLE_ENCODED_RE = re.compile(r"&amp;(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def _decode_html_entities_once(s: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name.startswith("#"):
            try:
                code = int(name[2:], 16) if name[1] in "xX" else int(name[1:])
                return chr(code)
            except (ValueError, OverflowError):
                return m.group(0)
        return _HTML_ENTITY_NAMED.get(name, m.group(0))

    return _HTML_ENTITY_RE.sub(repl, s)


def clean_publication_title(title: str | None) -> str | None:
    """Décode un titre double-encodé HTML, sinon le retourne tel quel.

    Détection : présence d'`&amp;` immédiatement suivi d'une entité connue
    (`lt`, `gt`, `amp`, `quot`, `apos`, `#NNN`, `#xHH`). Ce motif est la
    signature du double-encodage et ne se rencontre pas dans un titre
    normal (un `&amp;` isolé légitime style "Smith &amp; Jones" n'est pas
    suivi d'un nom d'entité, donc reste inchangé).

    Quand détecté, on décode deux niveaux pour retomber sur le HTML
    d'origine. Idempotent : un second appel sur le résultat ne change rien.
    """
    if not title or not _DOUBLE_ENCODED_RE.search(title):
        return title
    return _decode_html_entities_once(_decode_html_entities_once(title))


def extract_hal_id_from_url(url: str | None) -> str | None:
    """Extrait le HAL ID canonique d'une URL HAL ou d'un ID brut.

    Gère les préfixes hal/tel/halshs/inserm/pasteur/cea/ineris.
    Ignore le suffixe de version (v1, v2, etc.).

    >>> extract_hal_id_from_url("https://hal.science/hal-04123456v2")
    'hal-04123456'
    """
    return _normalize_hal_id(url)


# ── Règles métier d'agrégation multi-sources ────────────────────────

# Classement des statuts OA : plus la valeur est grande, plus le
# statut est « ouvert ». Utilisé par `best_oa_status` pour choisir le
# statut le plus ouvert entre plusieurs sources.
OA_RANK: dict[str, int] = {
    "diamond": 7,
    "gold": 6,
    "hybrid": 5,
    "bronze": 4,
    "green": 3,
    "closed": 2,
    "unknown": 1,
}

# Valeur canonique de `publications.oa_status` quand aucune source n'a
# de signal exploitable. Convention : `source_publications.oa_status`
# accepte NULL (= la source ne s'est pas prononcée), mais au niveau
# canonique on matérialise l'absence de signal par 'unknown' (vraie
# valeur de l'enum, classée en queue d'`OA_RANK`). À utiliser comme
# fallback après `best_oa_status(...)` ou pour défaut sur
# `source_publications.oa_status` orphelin.
OA_STATUS_UNKNOWN_DEFAULT = "unknown"


def best_oa_status(statuses: Iterable[str | None]) -> str | None:
    """Retourne le statut OA le plus ouvert parmi `statuses`.

    Ordre décroissant : diamond > gold > hybrid > bronze > green > closed > unknown.
    Les valeurs None, vides ou inconnues sont ignorées. Retourne None
    si aucune valeur exploitable n'est fournie.
    """
    best: str | None = None
    best_rank = 0
    for s in statuses:
        if not s:
            continue
        r = OA_RANK.get(s, 0)
        if r > best_rank:
            best, best_rank = s, r
    return best


# ── Règle de résolution de conflit sur DOI ──────────────────────────

_CHAPTER_DOC_TYPES: frozenset[str] = frozenset({"book_chapter", "book-chapter", "chapter"})
_BOOK_DOC_TYPES: frozenset[str] = frozenset({"book"})


@dataclass(frozen=True, slots=True)
class DoiConflictResolution:
    """Décision pure pour un conflit DOI entre deux documents.

    - `accepted_doi` : DOI à utiliser pour le nouveau document (None =
      ne pas lui attribuer ce DOI).
    - `merge_with_id` : id de la publication existante à fusionner avec
      (None = pas de fusion).
    - `clear_existing_doi` : True si le DOI doit être retiré de la
      publication existante (effet de bord à appliquer par l'appelant).
    """

    accepted_doi: str | None
    merge_with_id: int | None
    clear_existing_doi: bool


def resolve_doi_conflict(
    new_doi: str,
    new_doc_type: str,
    new_title_normalized: str,
    existing_doc_type: str | None,
    existing_title_normalized: str | None,
    existing_id: int,
) -> DoiConflictResolution:
    """Règle pure : gère les conflits de DOI entre chapitres et ouvrages.

    Quand un DOI existe déjà sur une publication d'un type incompatible
    (chapitre vs ouvrage), le DOI est retiré de l'un ou des deux côtés
    au lieu de fusionner. Dans tous les autres cas, les types sont
    considérés compatibles et on fusionne.
    """
    ex_type = existing_doc_type or ""

    # Chapitre vs ouvrage : le DOI est celui de l'ouvrage, pas du chapitre
    if new_doc_type in _CHAPTER_DOC_TYPES and ex_type in _BOOK_DOC_TYPES:
        return DoiConflictResolution(
            accepted_doi=None, merge_with_id=None, clear_existing_doi=False
        )

    if new_doc_type in _BOOK_DOC_TYPES and ex_type in _CHAPTER_DOC_TYPES:
        return DoiConflictResolution(
            accepted_doi=new_doi, merge_with_id=None, clear_existing_doi=True
        )

    # Deux chapitres avec titres différents : DOI erroné des deux côtés
    if new_doc_type in _CHAPTER_DOC_TYPES and ex_type in _CHAPTER_DOC_TYPES:
        ex_title = existing_title_normalized or ""
        if new_title_normalized != ex_title:
            return DoiConflictResolution(
                accepted_doi=None, merge_with_id=None, clear_existing_doi=True
            )
        return DoiConflictResolution(
            accepted_doi=new_doi, merge_with_id=existing_id, clear_existing_doi=False
        )

    # Cas normal : même DOI, types compatibles → fusion
    return DoiConflictResolution(
        accepted_doi=new_doi, merge_with_id=existing_id, clear_existing_doi=False
    )
