"""Règles sur les pays des publications.

Les pays d'une publication se lisent dans `publications.countries`, alimenté depuis les adresses de ses contributions sources. Les codes sont ceux de l'ISO 3166-1, en minuscules. Deux codes y ont une sémantique propre, que ce module nomme.
"""

import re
from enum import StrEnum

_COUNTRY_CODE = re.compile(r"^[a-z]{2}$")


def normalize_country_code(raw: str | None) -> str | None:
    """Code pays de `raw` en minuscules, ou `None` si `raw` n'a pas la forme d'un code à deux lettres (« -- »)."""
    code = (raw or "").strip().lower()
    return code if _COUNTRY_CODE.match(code) else None


class PlaceNameKind(StrEnum):
    """Nature d'une forme de `place_name_forms` (colonne `kind`). `COUNTRY` désigne un nom de pays, détecté en fin de segment d'adresse ; `INSTITUTION` et `CITY` désignent des expressions multi-mots (universités, CHU, villes), cherchées comme sous-chaînes et chacune associée à un pays."""

    COUNTRY = "country"
    INSTITUTION = "institution"
    CITY = "city"


# Code du référentiel réservé aux adresses dont aucun pays ne peut se déduire. Il occupe une
# ligne de `countries` pour qu'une adresse arbitrée « sans pays » se distingue d'une adresse
# non encore arbitrée, mais ne désigne aucun pays : les décomptes géographiques l'écartent.
NO_COUNTRY_CODE = "xx"

# Pays de l'établissement, dont dépend ce qu'une collaboration « internationale » recouvre.
# Paramètre d'établissement tenu ici en constante : les structures ne portent pas de pays, et
# le déduire des structures du périmètre reste à instruire.
DOMESTIC_COUNTRY_CODE = "fr"

# Codes qu'un décompte de collaboration internationale écarte : le pays de l'établissement,
# et l'absence de pays.
NON_INTERNATIONAL_COUNTRY_CODES: frozenset[str] = frozenset(
    {DOMESTIC_COUNTRY_CODE, NO_COUNTRY_CODE}
)
