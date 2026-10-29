"""Identifiants de personne, au contrat de `domain.identifiers.NormalizedIdentifier` : ORCID, IdHAL, IdRef (PPN SUDOC), compte HAL (`HalPersonId`).

`normalized_identifier_value` rend la forme normalisée d'une valeur selon son type, sans construire de value object.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import NamedTuple

from domain.errors import ValidationError
from domain.identifiers import NormalizedIdentifier
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


class ORCID(NormalizedIdentifier):
    """Open Researcher and Contributor ID, format XXXX-XXXX-XXXX-XXXX.

    Lève `ValidationError` si la valeur ne respecte pas le format. Contrôle le format, sans vérifier la checksum MOD 11-2.
    """

    label = "ORCID"
    normalize = staticmethod(normalize_orcid)


# ── IdHAL (personne) ───────────────────────────────────────────────

# Un IdHAL est une chaîne sans espace. Sa forme par défaut est `prenom-nom`.
_IDHAL_CANONICAL = re.compile(r"^\S+$")


def _normalize_idhal(raw: str | None) -> str | None:
    """Normalise un IdHAL personne : trim, lowercase, refuse une valeur vide ou qui contient un espace. HAL ne distingue pas la casse."""
    if not raw:
        return None
    s = raw.strip().lower()
    if not _IDHAL_CANONICAL.match(s):
        return None
    return s


class IdHAL(NormalizedIdentifier):
    """Identifiant IdHAL d'une personne, choisi par la personne à sa création.

    Ex. `jean-dupont`, `jdupont`, `jean.dupont`.
    """

    label = "IdHAL"
    normalize = staticmethod(_normalize_idhal)


# ── IdRef (PPN SUDOC) ──────────────────────────────────────────────

_IDREF_URL_RE = re.compile(r"idref\.fr/(\d{8}[\dX])(?:/id)?", re.IGNORECASE)
# PPN : 8 chiffres + 1 caractère de contrôle (chiffre ou X)
_IDREF_CANONICAL = re.compile(r"^\d{8}[\dX]$")


def _normalize_idref(raw: str | None) -> str | None:
    """Normalise un IdRef (PPN) : 9 caractères, dernier peut être X.

    Accepte une URL idref.fr en entrée. Les blancs sont retirés.
    """
    if not raw:
        return None
    s = "".join(raw.split())
    # URL éventuelle
    m = _IDREF_URL_RE.search(s)
    if m:
        s = m.group(1)
    s = s.upper()
    if not _IDREF_CANONICAL.match(s):
        return None
    return s


class IdRef(NormalizedIdentifier):
    """Identifiant IdRef (PPN SUDOC), format 8 chiffres + clé de contrôle."""

    label = "IdRef"
    normalize = staticmethod(_normalize_idref)


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


class HalPersonId(NormalizedIdentifier):
    """Identifiant d'un compte HAL (`personId`), entier positif."""

    label = "Compte HAL"
    normalize = staticmethod(_normalize_hal_person_id)


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


# ── Identifiants d'une contribution source (`contributor_information.identifiers`) ──


class ContributorIdentifiers(NamedTuple):
    """Identifiants d'une contribution source : `values` pour `contributor_information.identifiers`, `malformed` pour les couples `(type, valeur brute)` écartés."""

    values: dict[str, JsonValue] | None
    malformed: tuple[tuple[str, str], ...]


def compact_identifiers(**ids: str | int | None) -> ContributorIdentifiers:
    """Construit les identifiants d'une contribution source depuis les valeurs brutes de la source.

    Une valeur falsy (None, 0, "") est absente. Un identifiant de `PersonIdentifierType` prend la forme normalisée par le value object de son type ; une valeur mal formée va dans `malformed`. Les autres clés gardent leur valeur. Sans identifiant, `values` vaut None.
    """
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
