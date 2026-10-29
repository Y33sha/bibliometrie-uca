"""Identifiants de structure : ROR et code de collection HAL."""

import re
from collections.abc import Iterable

from domain.identifiers import NormalizedIdentifier

_ROR_URL_PREFIXES = (
    "https://ror.org/",
    "http://ror.org/",
    "ror.org/",
)
_ROR_CANONICAL = re.compile(r"^0[0-9a-hjkmnp-z]{8}$")


def normalize_ror_id(raw: str | None) -> str | None:
    """Forme courte d'un ROR, écrit seul ou dans une URL `ror.org` ; `None` si le format est invalide."""
    if not raw:
        return None
    s = raw.strip().lower()
    for prefix in _ROR_URL_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    s = s.strip()
    if not _ROR_CANONICAL.match(s):
        return None
    return s


class RorId(NormalizedIdentifier):
    """Identifiant ROR, sous forme courte : `0` et 8 caractères d'un alphabet sans i, l, o ni u. L'URL `https://ror.org/<id>` sert seulement à l'affichage."""

    label = "ROR"
    normalize = staticmethod(normalize_ror_id)


def parse_ror_ids(raws: Iterable[str | None]) -> frozenset[RorId]:
    """Ensemble des `RorId` valides de `raws`, URL ou identifiants courts. Les valeurs vides ou invalides sont écartées."""
    return frozenset(ror for raw in raws if (ror := RorId.try_parse(raw)) is not None)


# Code de collection HAL : lettres ASCII, chiffres, tiret et soulignement, d'après les codes observés. HAL n'en publie pas le format.
_HAL_COLLECTION_CANONICAL = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")


def normalize_hal_collection(raw: str | None) -> str | None:
    """Code de collection HAL en majuscules ; `None` s'il contient d'autres caractères."""
    if not raw:
        return None
    s = raw.strip().upper()
    if not _HAL_COLLECTION_CANONICAL.match(s):
        return None
    return s


class HalCollection(NormalizedIdentifier):
    """Code de collection HAL, en majuscules (`LIMOS`, `INSTITUT_PASCAL`)."""

    label = "Collection HAL"
    normalize = staticmethod(normalize_hal_collection)
