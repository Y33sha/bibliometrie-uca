"""Concept métier Personne — value objects, règles de composition,
modèles de données JSONB, et (à terme) entités.

Regroupe ici tout ce qui est propre à une personne : identifiants
(ORCID, IdHAL login, IdRef/PPN SUDOC), règles de composition des
formes de nom, modèles de colonnes JSONB (`source_ids`), puis plus
tard les entités `Person`, les règles de dédoublonnage, etc.

Les value objects sont immuables et auto-validés (même contrat que
domain/publication.py : `X("...")` strict, `X.try_parse(...)` tolérant).
"""

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from domain.errors import ValidationError
from domain.normalize import normalize_name

# ── Formes de noms (règle métier) ──────────────────────────────────


def compute_person_name_forms(last_name: str, first_name: str) -> set[str]:
    """Calcule les variantes normalisées de formes de nom pour une personne.

    Règle de composition du domaine (ne dépend d'aucune BD).

    Retourne un ensemble de formes normalisées :
      - "prenom nom", "nom prenom"
      - "initiale(s) nom", "nom initiale(s)"
        Si le prénom a plusieurs mots (ex: "jean michel"), produit :
        - initiales séparées : "j m nom", "nom j m"
        - initiales collées  : "jm nom", "nom jm"
    """
    ln = normalize_name(last_name)
    fn = normalize_name(first_name)
    if not ln:
        return set()

    forms: set[str] = set()
    if fn:
        forms.add(f"{fn} {ln}")
        forms.add(f"{ln} {fn}")

        parts = fn.split()
        if parts:
            initials_spaced = " ".join(p[0] for p in parts)
            initials_joined = "".join(p[0] for p in parts)
            forms.add(f"{initials_spaced} {ln}")
            forms.add(f"{ln} {initials_spaced}")
            if initials_joined != initials_spaced:
                forms.add(f"{initials_joined} {ln}")
                forms.add(f"{ln} {initials_joined}")
    else:
        forms.add(ln)

    return forms


# ── ORCID ──────────────────────────────────────────────────────────

_ORCID_URL_PREFIXES = ("https://orcid.org/", "http://orcid.org/", "orcid.org/")
# Format canonique : 4 groupes de 4 caractères, dernier peut être X (checksum)
_ORCID_CANONICAL = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def _normalize_orcid(raw: str | None) -> str | None:
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
        cleaned = _normalize_orcid(self.value)
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


# ── PersonSourceIds : colonne source_persons.source_ids ────────────


class PersonSourceIds(BaseModel):
    """Modèle de la colonne JSONB `source_ids` de `source_persons`.

    Identifiants **bruts** lus depuis les API sources (principalement
    HAL). Distinct de la table `person_identifiers` qui stocke le
    référentiel canonique (ORCID/idHAL/IdRef confirmés ou en attente,
    attachés à une personne consolidée).

    Ici on a par exemple :
    - `hal_person_id` : entier interne HAL (>0 = compte confirmé)
    - `idhal` : login slug HAL (validé via VO IdHAL)
    - `hal_form_id` : ID du formulaire HAL (structure interne)

    extra="allow" pour accepter d'autres clés que d'autres sources
    (ScanR, WoS, …) pourraient introduire à l'avenir.
    """

    model_config = ConfigDict(extra="allow")

    hal_person_id: int | None = None
    idhal: str | None = None
    hal_form_id: int | None = None

    @field_validator("idhal", mode="before")
    @classmethod
    def _normalize_idhal(cls, v: Any) -> str | None:
        """Normalise via le VO IdHAL : trim, lowercase, validation du slug."""
        if v is None or v == "":
            return None
        normalized = IdHAL.try_parse(v)
        if normalized is None:
            raise ValueError(f"IdHAL invalide : {v!r}")
        return normalized.value

    def to_dict(self) -> dict:
        """Sérialise pour écriture en base (JSONB). Omet les clés None."""
        return self.model_dump(exclude_none=True)
