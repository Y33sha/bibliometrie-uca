"""Concept métier Publication — value objects, modèles de données JSONB,
types de résultats de recherche et (à terme) entités.

Regroupe ici tout ce qui est propre à une publication : identifiants
(DOI, HAL ID document, NNT), modèles des colonnes JSONB
(`external_ids`, `meta`, `biblio`, `topics`), types de résultats
renvoyés par les repositories, puis plus tard les entités
`Publication`, les règles de déduplication, les invariants.

Les value objects sont immuables et auto-validés :
- construction stricte : `DOI("...")` lève ValidationError si invalide
- construction tolérante : `DOI.try_parse("...")` renvoie None quand
  l'absence est un cas normal (code pipeline qui tolère les données
  manquantes)
- la valeur stockée est toujours normalisée (canonique) : deux VO
  égaux par valeur, quel que soit le format d'entrée

Les modèles JSONB sont des Pydantic BaseModel : ils documentent les
clés attendues, valident à la construction (en réutilisant les VO
pour les identifiants), sérialisent en dict pour l'écriture en base.
"""

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

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
    """Normalise un DOI brut (préfixe URL, espaces, suffixe de version).

    Séparée de la classe pour rester appelable depuis utils/doi.py
    (compat avec les ~50 sites d'appel existants).
    """
    if not raw:
        return None
    s = raw.strip()
    lower = s.lower()
    for prefix in _DOI_URL_PREFIXES:
        if lower.startswith(prefix):
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


# ── ExternalIds : colonne source_publications.external_ids ─────────


class ExternalIds(BaseModel):
    """Modèle de la colonne JSONB `external_ids` des source_publications.

    Identifiants externes cross-source, utilisés notamment pour la
    déduplication (fusion par HAL-ID, par NNT, …). Les valeurs sont
    normalisées via les value objects du domaine — un HAL URL en entrée
    est stocké comme HAL ID canonique, un NNT est mis en majuscules, etc.

    `extra="allow"` autorise les clés non déclarées (arxiv, issn, …)
    pour ne pas bloquer l'évolution du schéma sur une clé nouvelle.
    Les clés déclarées ici sont les seules qui sont validées/normalisées.
    """

    model_config = ConfigDict(extra="allow")

    hal: str | None = None  # HAL ID document (ex. "hal-04123456")
    nnt: str | None = None  # Numéro National de Thèse
    pmid: str | None = None  # PubMed ID
    pmc: str | None = None  # PubMed Central ID

    @field_validator("hal", mode="before")
    @classmethod
    def _normalize_hal(cls, v: Any) -> str | None:
        """Normalise via HALId : URL → ID canonique, strip version."""
        if v is None or v == "":
            return None
        normalized = HALId.try_parse(v)
        if normalized is None:
            raise ValueError(f"HAL ID invalide : {v!r}")
        return normalized.value

    @field_validator("nnt", mode="before")
    @classmethod
    def _normalize_nnt(cls, v: Any) -> str | None:
        """Normalise via NNT : trim + uppercase."""
        if v is None or v == "":
            return None
        normalized = NNT.try_parse(v)
        if normalized is None:
            raise ValueError(f"NNT invalide : {v!r}")
        return normalized.value

    def to_dict(self) -> dict:
        """Sérialise pour écriture en base (JSONB).

        Omet les clés None pour garder des objets compacts côté BD.
        Préserve les clés supplémentaires (extra="allow").
        """
        return self.model_dump(exclude_none=True)


# ── PublicationBiblio : colonne biblio ─────────────────────────────


class PublicationBiblio(BaseModel):
    """Modèle de la colonne JSONB `biblio` (sur source_publications ET
    publications).

    Contient les infos bibliographiques d'un article (volume, issue,
    numéro de page). **Schéma hétérogène selon la source** :
    - HAL → `pages` (range ex. "123-456", potentiellement avec préfixe
      genre "S123-S145" pour supplément)
    - OpenAlex, WoS → `first_page` + `last_page` (décomposé)

    Les deux peuvent coexister dans la même ligne après fusion (le
    merge shallow de refresh_from_sources ne dédoublonne pas). Les
    champs sont **tous optionnels** — on accepte toutes les clés
    rencontrées sans chercher à les unifier, tant qu'on n'a pas tranché.
    """

    model_config = ConfigDict(extra="allow")

    volume: str | None = None
    issue: str | None = None
    pages: str | None = None  # HAL : range "123-456"
    first_page: str | None = None  # OpenAlex, WoS
    last_page: str | None = None  # OpenAlex, WoS

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


# ── PublicationMeta : colonne meta ─────────────────────────────────


class EcoleDoctorale(BaseModel):
    """École doctorale d'une thèse (metadata theses.fr)."""

    model_config = ConfigDict(extra="allow")
    nom: str
    ppn: str | None = None  # IdRef de l'ED quand disponible


class Partenaire(BaseModel):
    """Partenaire de recherche d'une thèse (metadata theses.fr)."""

    model_config = ConfigDict(extra="allow")
    nom: str
    type: str | None = None  # ex: "etablissement", "laboratoire", …


class PublicationMeta(BaseModel):
    """Modèle de la colonne JSONB `meta` (sur source_publications ET
    publications).

    Aujourd'hui peuplée uniquement par theses.fr (champs thèse :
    dates de soutenance/inscription, discipline, écoles doctorales,
    partenaires). Le modèle reste ouvert (extra="allow") pour
    accueillir d'autres types de métadonnées plus tard sans migration.

    `discipline` est la source de vérité pour la discipline d'une
    thèse (par convention dans le projet) — `topics.theses.discipline`
    en contient aussi une copie historique qu'il faudra purger.
    """

    model_config = ConfigDict(extra="allow")

    # Dates au format ISO 8601 (YYYY-MM-DD) — stockées en string dans
    # le JSONB, pas de type date Pydantic pour simplifier la sérialisation.
    date_soutenance: str | None = None
    date_inscription: str | None = None

    discipline: str | None = None
    ecoles_doctorales: list[EcoleDoctorale] | None = None
    partenaires: list[Partenaire] | None = None

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


# ── PublicationTopics : colonne topics ─────────────────────────────


class OpenAlexTopic(BaseModel):
    """Un élément de la hiérarchie thématique OpenAlex.

    Un document a plusieurs lignes de ce type (une liste de OpenAlexTopic)
    car OpenAlex classe souvent en plusieurs sujets avec des scores.
    Tous les champs sont optionnels par défensivité (données réelles
    parfois incomplètes).
    """

    model_config = ConfigDict(extra="allow")

    domain: str | None = None
    field: str | None = None
    subfield: str | None = None
    topic: str | None = None
    score: float | None = None


class ThesesTopics(BaseModel):
    """Topics au format theses.fr : discipline + termes Rameau.

    `discipline` est une copie de `meta.discipline` — il est redondant
    mais présent dans les données historiques. Voir PublicationMeta.
    """

    model_config = ConfigDict(extra="allow")

    discipline: str | None = None
    rameau: list[str] | None = None


class PublicationTopics(BaseModel):
    """Modèle de la colonne JSONB `topics` (sur publications,
    reconstituée par refresh_from_sources).

    **Container composite par source** — chaque source garde sa forme
    native, rien n'est perdu (cf. commit précédent qui a corrigé
    la perte silencieuse des topics OpenAlex) :
    - openalex : liste de OpenAlexTopic (hiérarchie thématique)
    - theses   : dict discipline+rameau
    - scanr    : dict non contrôlé (structure variable)

    Sur `source_publications.topics`, chaque ligne contient UNE seule
    forme (la forme native de la source). Sur `publications.topics`,
    le dict indexé par source est reconstitué à partir des sources.
    """

    model_config = ConfigDict(extra="allow")

    openalex: list[OpenAlexTopic] | None = None
    theses: ThesesTopics | None = None
    scanr: dict | None = None  # format variable, pas de sous-modèle

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


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


def extract_hal_id_from_url(url: str | None) -> str | None:
    """Extrait le HAL ID canonique d'une URL HAL ou d'un ID brut.

    Gère les préfixes hal/tel/halshs/inserm/pasteur/cea/ineris.
    Ignore le suffixe de version (v1, v2, etc.).

    >>> extract_hal_id_from_url("https://hal.science/hal-04123456v2")
    'hal-04123456'
    """
    return _normalize_hal_id(url)
