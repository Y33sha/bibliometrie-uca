"""Codes pays (ISO 3166-1, en minuscules) et codes réservés."""

import re
from enum import StrEnum

_COUNTRY_CODE = re.compile(r"^[a-z]{2}$")

NO_COUNTRY_CODE = "xx"
"""Code « non applicable », posé sur une adresse arbitrée sans pays. Il distingue cette adresse d'une adresse non arbitrée. Les décomptes géographiques l'écartent."""


FRANCE_CODE = "fr"

FRENCH_OVERSEAS_CODES = frozenset(
    {"bl", "gf", "gp", "mf", "mq", "nc", "pf", "pm", "re", "tf", "wf", "yt"}
)
"""Codes ISO 3166-1 de l'outre-mer français : départements et régions, collectivités, Nouvelle-Calédonie, Terres australes et antarctiques. `normalize_country_code` les remplace par `FRANCE_CODE`."""


def normalize_country_code(raw: str | None) -> str | None:
    """Renvoie le code pays de `raw` en minuscules, `FRANCE_CODE` pour un code de l'outre-mer français, ou `None` si `raw` n'a pas la forme d'un code à deux lettres (« -- ») ou vaut le code réservé `NO_COUNTRY_CODE`."""
    code = (raw or "").strip().lower()
    if not _COUNTRY_CODE.match(code) or code == NO_COUNTRY_CODE:
        return None
    return FRANCE_CODE if code in FRENCH_OVERSEAS_CODES else code


class PlaceNameKind(StrEnum):
    """Nature d'un nom de lieu associé à un pays."""

    COUNTRY = "country"
    INSTITUTION = "institution"
    CITY = "city"


def non_international_country_codes(institution_country: str) -> list[str]:
    """Renvoie les codes écartés des décomptes de collaborations internationales : pays de l'établissement et absence de pays."""
    return sorted({institution_country, NO_COUNTRY_CODE})
