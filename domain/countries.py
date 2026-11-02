"""Codes pays (ISO 3166-1, en minuscules) et codes réservés."""

import re
from enum import StrEnum

_COUNTRY_CODE = re.compile(r"^[a-z]{2}$")

# Code « non applicable », posé sur une adresse arbitrée sans pays. Il distingue cette adresse d'une adresse non arbitrée. Les décomptes géographiques l'écartent.
NO_COUNTRY_CODE = "xx"


def normalize_country_code(raw: str | None) -> str | None:
    """Renvoie le code pays de `raw` en minuscules, ou `None` si `raw` n'a pas la forme d'un code à deux lettres (« -- ») ou vaut le code réservé `NO_COUNTRY_CODE`."""
    code = (raw or "").strip().lower()
    return code if _COUNTRY_CODE.match(code) and code != NO_COUNTRY_CODE else None


class PlaceNameKind(StrEnum):
    """Nature d'un nom de lieu associé à un pays."""

    COUNTRY = "country"
    INSTITUTION = "institution"
    CITY = "city"


def non_international_country_codes(institution_country: str) -> list[str]:
    """Renvoie les codes écartés des décomptes de collaborations internationales : pays de l'établissement et absence de pays."""
    return sorted({institution_country, NO_COUNTRY_CODE})
