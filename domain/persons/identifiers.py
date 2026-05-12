"""Value objects et helpers de normalisation des identifiants personne.

ORCID, IdHAL (login HAL en forme slug), IdRef (PPN SUDOC). Trois VOs
immuables et auto-validés au même contrat que ``domain/publication.py`` :

- ``X("...")`` strict : lève ``ValidationError`` si malformé
- ``X.try_parse(...)`` tolérant : renvoie None si malformé

Les helpers ``normalize_*`` sont exposés indépendamment pour les call
sites qui veulent juste normaliser sans construire un VO (typiquement
les normalizers de pipeline qui stockent la forme texte en base).
"""

import re
from dataclasses import dataclass

from domain.errors import ValidationError
from domain.json_types import JsonValue

# ── Types d'identifiants côté référentiel personnes ───────────────
#
# Deux listes, à ne pas confondre :
#
# - `PERSON_IDENTIFIER_TYPES` : liste **complète** des id_types
#   admissibles dans la table `person_identifiers`. Utilisée par la
#   promotion canonique depuis les `source_authorships`
#   (`add_identifiers_from_authorships`). Inclut `hal_person_id` —
#   identifiant interne HAL conservé pour la dédup cross-source mais
#   **jamais exposé en UI**.
#
# - `PUBLIC_PERSON_IDENTIFIER_TYPES` : sous-ensemble **visible UI**.
#   Utilisée par les filtres SQL côté lecture (page personne, liste
#   persons, doublons) et par la validation des routes d'ajout par
#   l'utilisatrice. `hal_person_id` exclu pour ne jamais le faire
#   remonter dans l'UI.
#
# Tout nouvel id_type accepté en base doit être ajouté à au moins
# `PERSON_IDENTIFIER_TYPES`, et à `PUBLIC_...` s'il doit apparaître
# en UI.

PERSON_IDENTIFIER_TYPES: tuple[str, ...] = ("orcid", "idhal", "idref", "hal_person_id")
PUBLIC_PERSON_IDENTIFIER_TYPES: tuple[str, ...] = ("orcid", "idhal", "idref")

# ── ORCID ──────────────────────────────────────────────────────────

_ORCID_URL_PREFIXES = ("https://orcid.org/", "http://orcid.org/", "orcid.org/")
# Format canonique : 4 groupes de 4 caractères, dernier peut être X (checksum)
_ORCID_CANONICAL = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def normalize_orcid(raw: str | None) -> str | None:
    """Normalise un ORCID : supprime le préfixe URL, met les hyphens en forme.

    Accepte les variantes avec ou sans URL, avec ou sans hyphens.
    Renvoie None si la normalisation échoue ou si le format est invalide.
    """
    if not raw:
        return None
    s = raw.strip()
    # Strip URL prefix (casse-insensible)
    lower = s.lower()
    for prefix in _ORCID_URL_PREFIXES:
        if lower.startswith(prefix):
            s = s[len(prefix) :]
            break
    s = s.strip().upper()  # X en majuscule
    # Forme sans hyphens → ajouter les hyphens
    if "-" not in s and len(s) == 16:
        s = f"{s[0:4]}-{s[4:8]}-{s[8:12]}-{s[12:16]}"
    if not _ORCID_CANONICAL.match(s):
        return None
    return s


@dataclass(frozen=True)
class ORCID:
    """Open Researcher and Contributor ID, format XXXX-XXXX-XXXX-XXXX.

    Lève ValidationError si la valeur ne respecte pas le format. Ne
    valide pas la checksum MOD 11-2 (à ajouter si besoin ultérieurement).
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = normalize_orcid(self.value)
        if not cleaned:
            raise ValidationError(f"ORCID invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "ORCID | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── IdHAL (personne) ───────────────────────────────────────────────

# Slug HAL : minuscules, chiffres, tirets. Les anciens comptes peuvent
# aussi être numériques (l'API HAL distingue idHal_s et idHal_i). On
# accepte les deux formes, stockées en base comme texte.
_IDHAL_CANONICAL = re.compile(r"^[a-z0-9][a-z0-9-]{1,59}$")


def _normalize_idhal(raw: str | None) -> str | None:
    """Normalise un IdHAL personne : trim, lowercase, vérifie la forme slug."""
    if not raw:
        return None
    s = raw.strip().lower()
    if not _IDHAL_CANONICAL.match(s):
        return None
    return s


@dataclass(frozen=True)
class IdHAL:
    """Identifiant IdHAL d'une personne (login HAL, forme slug).

    Ex. `jean-dupont`, `jdupont`, ou numérique pour les anciens comptes.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_idhal(self.value)
        if not cleaned:
            raise ValidationError(f"IdHAL invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "IdHAL | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── IdRef (PPN SUDOC) ──────────────────────────────────────────────

_IDREF_URL_RE = re.compile(r"idref\.fr/(\d{8}[\dX])(?:/id)?", re.IGNORECASE)
# PPN : 8 chiffres + 1 caractère de contrôle (chiffre ou X)
_IDREF_CANONICAL = re.compile(r"^\d{8}[\dX]$")


def _normalize_idref(raw: str | None) -> str | None:
    """Normalise un IdRef (PPN) : 9 caractères, dernier peut être X.

    Accepte une URL idref.fr en entrée.
    """
    if not raw:
        return None
    s = raw.strip()
    # URL éventuelle
    m = _IDREF_URL_RE.search(s)
    if m:
        s = m.group(1)
    s = s.upper()
    if not _IDREF_CANONICAL.match(s):
        return None
    return s


@dataclass(frozen=True)
class IdRef:
    """Identifiant IdRef (PPN SUDOC), format 8 chiffres + clé de contrôle."""

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_idref(self.value)
        if not cleaned:
            raise ValidationError(f"IdRef invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "IdRef | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── Construction du dict JSONB `source_authorships.person_identifiers` ────


def compact_identifiers(**ids: JsonValue) -> dict[str, JsonValue] | None:
    """Construit le dict d'identifiants pour ``source_authorships.person_identifiers``.

    Convention : valeur falsy (None, 0, "", …) → clé absente du dict,
    dict vide → None.
    """
    out: dict[str, JsonValue] = {k: v for k, v in ids.items() if v}
    return out or None
