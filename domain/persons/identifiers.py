"""Value objects et helpers de normalisation des identifiants personne.

ORCID, IdHAL (login HAL en forme slug), IdRef (PPN SUDOC). Trois VOs immuables et auto-validés au même contrat que `domain/publications/identifiers.py` :

- `X("...")` strict : lève `ValidationError` si malformé
- `X.try_parse(...)` tolérant : renvoie None si malformé

`normalized_identifier_value` rend la forme normalisée d'une valeur selon son type, sans construire de VO.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from domain.errors import ValidationError
from domain.types import JsonValue


class IdentifierOrigin(StrEnum):
    """Origine d'une attribution `IdentifierAttribution ↔ Person`, valeur de l'enum Postgres `identifier_origin`."""

    MANUAL = "manual"
    """Décision d'une utilisatrice."""
    AUTO = "auto"
    """Résolution par le pipeline."""


class AttributionStatus(StrEnum):
    """Statut d'une attribution `IdentifierAttribution ↔ Person`.

    Mappe sur l'enum Postgres `identifier_status`. `StrEnum` garde la valeur sérialisable telle quelle vers SQL et API.

    L'admin pose librement `PENDING`, `CONFIRMED` ou `REJECTED` (`update_identifier_status`). Le pipeline passe par les méthodes de `IdentifierAttribution` : `reattribute_to` reprend un identifiant `REJECTED` chez une autre personne, `transfer_to` déplace un identifiant `PENDING`.

    `AUTHENTICATED` est un statut à part : il atteste que le chercheur a lui-même authentifié son ORCID en se connectant à son compte. Seul un ORCID peut le porter. C'est le statut le plus fort et le seul immuable : un trigger Postgres interdit d'en sortir (aucune dégradation, même par l'admin) et de le poser hors de l'import dédié des ORCID authentifiés. Il ne participe à aucune transition applicative.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    AUTHENTICATED = "authenticated"


# ── Types d'identifiants côté référentiel personnes ───────────────


class PersonIdentifierType(StrEnum):
    """Type d'un identifiant de personne, valeur de `person_identifiers.id_type`. `hal_person_id` désigne un compte HAL (`personId`)."""

    ORCID = "orcid"
    IDHAL = "idhal"
    IDREF = "idref"
    HAL_PERSON_ID = "hal_person_id"


PERSON_IDENTIFIER_LABELS: dict[PersonIdentifierType, str] = {
    PersonIdentifierType.ORCID: "ORCID",
    PersonIdentifierType.IDHAL: "idHAL",
    PersonIdentifierType.IDREF: "IdRef",
    PersonIdentifierType.HAL_PERSON_ID: "compte HAL",
}

# Deux vues du vocabulaire :
#
# - `PERSON_IDENTIFIER_TYPES` : tous les types admissibles dans `person_identifiers`. La promotion depuis les `source_contributions` (`add_identifiers_from_contributions`) et l'interface d'administration les couvrent tous.
# - `PUBLIC_PERSON_IDENTIFIER_TYPES` : les types de l'interface publique, seuls attribuables à la main. `hal_person_id` en est exclu : l'extraction l'observe dans le TEI HAL.
#
# Un type ajouté à l'enum entre automatiquement dans `PERSON_IDENTIFIER_TYPES`, et dans `PUBLIC_...` seulement s'il doit apparaître dans l'interface publique.

PERSON_IDENTIFIER_TYPES: tuple[PersonIdentifierType, ...] = tuple(PersonIdentifierType)
PUBLIC_PERSON_IDENTIFIER_TYPES: tuple[PersonIdentifierType, ...] = (
    PersonIdentifierType.ORCID,
    PersonIdentifierType.IDHAL,
    PersonIdentifierType.IDREF,
)

# ── ORCID ──────────────────────────────────────────────────────────

_ORCID_URL_PREFIXES = ("https://orcid.org/", "http://orcid.org/", "orcid.org/")
# Format canonique : 4 groupes de 4 caractères, dernier peut être X (checksum)
_ORCID_CANONICAL = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def normalize_orcid(raw: str | None) -> str | None:
    """Normalise un ORCID : supprime le préfixe URL, met les hyphens en forme.

    Accepte les variantes avec ou sans URL, avec ou sans hyphens. Renvoie None si la normalisation échoue ou si le format est invalide.
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


def orcid_uri(orcid: str) -> str:
    """Forme URI d'un ORCID normalisé : `https://orcid.org/XXXX-XXXX-XXXX-XXXX`."""
    return f"{_ORCID_URL_PREFIXES[0]}{orcid}"


@dataclass(frozen=True)
class ORCID:
    """Open Researcher and Contributor ID, format XXXX-XXXX-XXXX-XXXX.

    Lève `ValidationError` si la valeur ne respecte pas le format. Contrôle le format, sans vérifier la checksum MOD 11-2.
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

# Slug HAL : minuscules, chiffres, tirets. Certains comptes sont numériques
# (l'API HAL distingue idHal_s et idHal_i). On accepte les deux formes,
# stockées en base comme texte.
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

    Ex. `jean-dupont`, `jdupont`, ou une forme numérique.
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


# ── hal_person_id (compte HAL) ────────────────────────────────────

# `personId` HAL : entier positif.
_HAL_PERSON_ID_CANONICAL = re.compile(r"^[1-9][0-9]*$")


def _normalize_hal_person_id(raw: str | None) -> str | None:
    """Normalise un hal_person_id : entier positif sous forme de chaîne."""
    if not raw:
        return None
    s = str(raw).strip()
    if not _HAL_PERSON_ID_CANONICAL.match(s):
        return None
    return s


@dataclass(frozen=True)
class HalPersonId:
    """Identifiant d'un compte HAL (`personId`), entier positif."""

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_hal_person_id(self.value)
        if not cleaned:
            raise ValidationError(f"hal_person_id invalide : {self.value!r}")
        object.__setattr__(self, "value", cleaned)

    @classmethod
    def try_parse(cls, raw: str | None) -> "HalPersonId | None":
        if not raw:
            return None
        try:
            return cls(raw)
        except ValidationError:
            return None

    def __str__(self) -> str:
        return self.value


# ── Validation d'un identifiant par type ──────────────────────────

_IDENTIFIER_VALUE_OBJECTS: dict[str, type[ORCID | IdHAL | IdRef | HalPersonId]] = {
    PersonIdentifierType.ORCID: ORCID,
    PersonIdentifierType.IDHAL: IdHAL,
    PersonIdentifierType.IDREF: IdRef,
    PersonIdentifierType.HAL_PERSON_ID: HalPersonId,
}


def normalized_identifier_value(id_type: str, raw: str) -> str:
    """Valide et normalise la valeur d'un identifiant via le value object de son type.

    Point d'entrée unique de validation avant écriture : délègue au VO auto-validé du type et renvoie la forme canonique stockée en base. Couvre les quatre types de `PERSON_IDENTIFIER_TYPES`. Lève `ValidationError` si le type est inconnu ou si la valeur est malformée — à l'appelant de décider (rejet 4xx côté API, log et poursuite côté pipeline).
    """
    value_object = _IDENTIFIER_VALUE_OBJECTS.get(id_type)
    if value_object is None:
        raise ValidationError(f"Type d'identifiant inconnu : {id_type!r}")
    return value_object(raw).value


# ── Construction du dict JSONB `source_contributions.identifiers` ────


def compact_identifiers(**ids: JsonValue) -> dict[str, JsonValue] | None:
    """Construit le dict d'identifiants pour `source_contributions.identifiers`.

    Convention : valeur falsy (None, 0, "", …) → clé absente du dict, dict vide → None.
    """
    out: dict[str, JsonValue] = {k: v for k, v in ids.items() if v}
    return out or None


class IdentifierNeutralization(StrEnum):
    """Motif pour lequel une contribution source neutralise un identifiant de ses informations du contributeur : l'identifiant reste enregistré, et la résolution des personnes l'ignore pour cette contribution source."""

    SHARED = "shared"
    """Valeur portée par plusieurs contributions sources d'un même enregistrement source."""
    MISPLACED = "misplaced"
    """Valeur dont le consensus désigne une autre personne que le nom de la contribution source."""


def shared_identifier_neutralizations(
    ids_by_source_contribution: Sequence[Mapping[str, JsonValue] | None],
) -> list[dict[str, IdentifierNeutralization] | None]:
    """Identifiants neutralisés de chaque contribution source d'un enregistrement source, pour cause de partage.

    Une valeur d'identifiant, quel que soit son type, présente sur plusieurs contributions sources d'un même enregistrement source est une corruption : un identifiant désigne une seule contribution source par enregistrement source. Toute contribution source qui contient une valeur partagée voit tous ses identifiants neutralisés, y compris celle du vrai propriétaire, que rien ne distingue des autres. `None` pour une contribution source sans identifiant neutralisé.
    """
    counts: Counter[tuple[str, JsonValue]] = Counter()
    for ids in ids_by_source_contribution:
        if ids:
            counts.update(ids.items())
    shared = {kv for kv, n in counts.items() if n >= 2}
    return [
        dict.fromkeys(ids, IdentifierNeutralization.SHARED)
        if ids and any(kv in shared for kv in ids.items())
        else None
        for ids in ids_by_source_contribution
    ]
