"""Concept métier Publication — value objects et (à terme) entités.

Regroupe ici tout ce qui est propre à une publication : identifiants
(DOI, HAL ID document, NNT), puis plus tard les entités `Publication`,
les règles de déduplication, les invariants métier.

Les value objects sont immuables et auto-validés :
- construction stricte : `DOI("...")` lève ValidationError si invalide
- construction tolérante : `DOI.try_parse("...")` renvoie None quand
  l'absence est un cas normal (code pipeline qui tolère les données
  manquantes)
- la valeur stockée est toujours normalisée (canonique) : deux VO
  égaux par valeur, quel que soit le format d'entrée
"""

import re
from dataclasses import dataclass

from domain.errors import ValidationError

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
            s = s[len(prefix):]
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
_HAL_DOC_BASE = re.compile(
    rf"((?:{'|'.join(_HAL_DOC_PREFIXES)})-\d+)", re.IGNORECASE
)


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
