"""Value objects des identifiants bibliométriques.

Chaque identifiant est un objet-valeur immuable et auto-validé :
- construction stricte : `DOI("...")` lève ValidationError si la valeur
  est invalide ou vide
- construction tolérante : `DOI.try_parse("...")` renvoie None si l'entrée
  est inutilisable (pratique pour le code pipeline qui accepte l'absence
  de donnée)
- la valeur stockée est toujours normalisée (canonique) : on peut
  comparer deux identifiants par égalité de valeur sans se soucier des
  variantes d'écriture (préfixes URL, casse, suffixes de version, etc.)
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
