"""Codes pays (ISO 3166-1, en minuscules) et codes réservés."""

import re
from enum import StrEnum

_COUNTRY_CODE = re.compile(r"^[a-z]{2}$")


def normalize_country_code(raw: str | None) -> str | None:
    """Code pays de `raw` en minuscules, ou `None` si `raw` n'a pas la forme d'un code à deux lettres (« -- »)."""
    code = (raw or "").strip().lower()
    return code if _COUNTRY_CODE.match(code) else None


class PlaceNameKind(StrEnum):
    """Nature d'un nom de lieu associé à un pays."""

    COUNTRY = "country"
    INSTITUTION = "institution"
    CITY = "city"


# Code « non applicable », posé sur une adresse arbitrée sans pays. Il distingue cette adresse
# d'une adresse non arbitrée. Les décomptes géographiques l'écartent.
NO_COUNTRY_CODE = "xx"

# Pays de l'établissement.
DOMESTIC_COUNTRY_CODE = "fr"

# Codes écartés des décomptes de collaborations internationales.
NON_INTERNATIONAL_COUNTRY_CODES: frozenset[str] = frozenset(
    {DOMESTIC_COUNTRY_CODE, NO_COUNTRY_CODE}
)
