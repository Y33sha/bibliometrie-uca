"""Règles sur les pays des publications.

Les pays d'une publication se lisent dans `publications.countries`, alimenté depuis les adresses de ses signatures. Deux codes y portent une sémantique propre, que ce module nomme.
"""

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
