"""Identifiants de personne (ORCID, IdHAL, IdRef, compte HAL), leur forme normalisée et leur neutralisation."""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import NamedTuple

from domain.errors import ValidationError
from domain.identifiers import NormalizedIdentifier
from domain.types import JsonValue


class IdentifierOrigin(StrEnum):
    """Origine d'une attribution d'identifiant. Reflet du type PostgreSQL `identifier_origin`."""

    MANUAL = "manual"
    """Décision d'une utilisatrice."""
    AUTO = "auto"
    """Résolution par le pipeline."""


class AttributionStatus(StrEnum):
    """Statut d'une attribution d'identifiant. Reflet du type PostgreSQL `identifier_status`.

    L'administration pose librement `PENDING`, `CONFIRMED` ou `REJECTED`. Le pipeline change le statut par les méthodes de `IdentifierAttribution`.

    `AUTHENTICATED` atteste que le chercheur a authentifié son ORCID en se connectant à son compte. Seul un ORCID a ce statut. Un trigger PostgreSQL le rend définitif, et le réserve à l'import des ORCID authentifiés.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    AUTHENTICATED = "authenticated"


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

PERSON_IDENTIFIER_TYPES: tuple[PersonIdentifierType, ...] = tuple(PersonIdentifierType)
# Types de l'interface publique, seuls attribuables à la main. Le compte HAL vient seulement du moissonnage de HAL.
PUBLIC_PERSON_IDENTIFIER_TYPES: tuple[PersonIdentifierType, ...] = (
    PersonIdentifierType.ORCID,
    PersonIdentifierType.IDHAL,
    PersonIdentifierType.IDREF,
)

_ORCID_URL_PREFIXES = ("https://orcid.org/", "http://orcid.org/", "orcid.org/")
# Le dernier caractère, clé de contrôle, peut valoir X.
_ORCID_CANONICAL = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def normalize_orcid(raw: str | None) -> str | None:
    """Forme normalisée d'un ORCID (`0000-0002-1825-0097`), écrit avec ou sans URL, avec ou sans tirets ; `None` si le format est invalide."""
    if not raw:
        return None
    s = raw.strip()
    lower = s.lower()
    for prefix in _ORCID_URL_PREFIXES:
        if lower.startswith(prefix):
            s = s[len(prefix) :]
            break
    s = s.strip().upper()
    if "-" not in s and len(s) == 16:
        s = f"{s[0:4]}-{s[4:8]}-{s[8:12]}-{s[12:16]}"
    if not _ORCID_CANONICAL.match(s):
        return None
    return s


def orcid_uri(orcid: str) -> str:
    """Forme URI d'un ORCID normalisé : `https://orcid.org/XXXX-XXXX-XXXX-XXXX`."""
    return f"{_ORCID_URL_PREFIXES[0]}{orcid}"


class ORCID(NormalizedIdentifier):
    """ORCID. Seul le format est contrôlé, sans la clé de contrôle MOD 11-2."""

    label = "ORCID"
    normalize = staticmethod(normalize_orcid)


# Un IdHAL est une chaîne sans espace. Sa forme par défaut est `prenom-nom`.
_IDHAL_CANONICAL = re.compile(r"^\S+$")


def _normalize_idhal(raw: str | None) -> str | None:
    """IdHAL en minuscules (HAL ignore la casse) ; `None` s'il contient un espace."""
    if not raw:
        return None
    s = raw.strip().lower()
    if not _IDHAL_CANONICAL.match(s):
        return None
    return s


class IdHAL(NormalizedIdentifier):
    """IdHAL, choisi par la personne elle-même : `jean-dupont`, `jdupont`, `jean.dupont`."""

    label = "IdHAL"
    normalize = staticmethod(_normalize_idhal)


_IDREF_URL_RE = re.compile(r"idref\.fr/(\d{8}[\dX])(?:/id)?", re.IGNORECASE)
# PPN : 8 chiffres + 1 caractère de contrôle (chiffre ou X)
_IDREF_CANONICAL = re.compile(r"^\d{8}[\dX]$")


def _normalize_idref(raw: str | None) -> str | None:
    """Forme normalisée d'un IdRef, écrit seul ou dans une URL idref.fr ; `None` si le format est invalide."""
    if not raw:
        return None
    s = "".join(raw.split())
    m = _IDREF_URL_RE.search(s)
    if m:
        s = m.group(1)
    s = s.upper()
    if not _IDREF_CANONICAL.match(s):
        return None
    return s


class IdRef(NormalizedIdentifier):
    """IdRef (PPN du Sudoc) : 8 chiffres et une clé de contrôle."""

    label = "IdRef"
    normalize = staticmethod(_normalize_idref)


_HAL_PERSON_ID_CANONICAL = re.compile(r"^[1-9][0-9]*$")


def _normalize_hal_person_id(raw: str | None) -> str | None:
    """Identifiant de compte HAL ; `None` s'il n'est pas un entier positif."""
    if not raw:
        return None
    s = str(raw).strip()
    if not _HAL_PERSON_ID_CANONICAL.match(s):
        return None
    return s


class HalPersonId(NormalizedIdentifier):
    """Identifiant d'un compte HAL (`personId`), entier positif."""

    label = "Compte HAL"
    normalize = staticmethod(_normalize_hal_person_id)


_IDENTIFIER_VALUE_OBJECTS: dict[str, type[ORCID | IdHAL | IdRef | HalPersonId]] = {
    PersonIdentifierType.ORCID: ORCID,
    PersonIdentifierType.IDHAL: IdHAL,
    PersonIdentifierType.IDREF: IdRef,
    PersonIdentifierType.HAL_PERSON_ID: HalPersonId,
}


def normalized_identifier_value(id_type: str, raw: str) -> str:
    """Forme normalisée de la valeur d'un identifiant de personne. Lève `ValidationError` pour un type inconnu ou une valeur mal formée."""
    value_object = _IDENTIFIER_VALUE_OBJECTS.get(id_type)
    if value_object is None:
        raise ValidationError(f"Type d'identifiant inconnu : {id_type!r}")
    return value_object(raw).value


class ContributorIdentifiers(NamedTuple):
    """Identifiants d'une contribution source : `values` pour `contributor_information.identifiers`, `malformed` pour les couples `(type, valeur brute)` écartés."""

    values: dict[str, JsonValue] | None
    malformed: tuple[tuple[str, str], ...]


def compact_identifiers(**ids: str | int | None) -> ContributorIdentifiers:
    """Identifiants d'une contribution source, d'après les valeurs brutes de la source. Une valeur vide ou nulle est ignorée. Un identifiant de personne prend sa forme normalisée, ou va dans `malformed`. Les autres identifiants restent tels quels."""
    values: dict[str, JsonValue] = {}
    malformed: list[tuple[str, str]] = []
    for id_type, raw in ids.items():
        if not raw:
            continue
        value_object = _IDENTIFIER_VALUE_OBJECTS.get(id_type)
        if value_object is None:
            values[id_type] = raw
        elif parsed := value_object.try_parse(str(raw)):
            values[id_type] = parsed.value
        else:
            malformed.append((id_type, str(raw)))
    return ContributorIdentifiers(values or None, tuple(malformed))


class IdentifierNeutralization(StrEnum):
    """Motif de neutralisation d'un identifiant d'une contribution source : l'identifiant reste enregistré, et la résolution des personnes l'ignore pour cette contribution source."""

    SHARED = "shared"
    """Valeur présente dans plusieurs contributions sources d'un même enregistrement source."""
    MISPLACED = "misplaced"
    """Valeur dont le consensus désigne une autre personne que le nom de la contribution source."""


def shared_identifier_neutralizations(
    ids_by_source_contribution: Sequence[Mapping[str, JsonValue] | None],
) -> list[dict[str, IdentifierNeutralization] | None]:
    """Identifiants neutralisés de chaque contribution source d'un enregistrement source, pour partage d'une valeur. `None` pour une contribution source sans identifiant neutralisé.

    Un identifiant désigne un seul auteur d'un enregistrement source : une valeur partagée est une corruption. Toute contribution source qui la contient voit tous ses identifiants neutralisés, vrai propriétaire compris, faute de le distinguer.
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
