"""Niveau d'un titre de conteneur : série (revue, collection, série d'actes) ou volume (livre, volume d'actes).

Un titre qui désigne une édition ou un tome précis est celui d'un volume : une année (« NuFACT 2022 »), un ordinal d'édition (« 8th International Conference », « 34es Journées »), un numéro de volume (« LIPIcs, Volume 364 »). Un titre sans aucune de ces marques est celui d'une série. La clé de série d'un titre de volume retire ces marques : les volumes d'une même série la partagent.
"""

import re
from enum import StrEnum

from domain.journals.titles import names_a_dated_event
from domain.normalize import normalize_text

# Ordinal d'édition, anglais (« 8th », « 21st »), français (« 34es », « 6èmes », « 1re »), allemand (« 74. Jahrestagung »).
# Un siècle n'est pas une édition : « 19th-century », « XVIe siècle ».
_ORDINAL = re.compile(
    r"\b\d{1,3}(?:st|nd|rd|th|e|es|è|ème|èmes|eme|emes|er|re|ère)\b(?![\s-]*(?:centur|siècle|siecle))"
    r"|\b\d{1,3}\.\s+(?=[A-Za-zÀ-ÿ])",
    re.IGNORECASE,
)
# Numéro de volume ou de tome : « Volume 364 », « Vol. 3 », « Tome 2 », « Band 12 ».
_VOLUME_NUMBER = re.compile(r"\b(?:vol(?:ume)?|tome|band|bd)\.?\s*\d+\b", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(?:1[89]\d\d|20\d\d)(?!\d)")


class ContainerLevel(StrEnum):
    """Niveau d'un conteneur."""

    SERIES = "series"
    VOLUME = "volume"


def container_level(title: str) -> ContainerLevel:
    """Niveau d'un titre de conteneur, d'après ses marques d'édition ou de tome."""
    if names_a_dated_event(title) or _ORDINAL.search(title) or _VOLUME_NUMBER.search(title):
        return ContainerLevel.VOLUME
    return ContainerLevel.SERIES


def series_key(title: str) -> str:
    """Clé de série d'un titre : le titre normalisé, sans années, ordinaux d'édition ni numéros de volume. « NuFACT 2022 » et « NuFACT 2023 » partagent la clé « nufact »."""
    for pattern in (_VOLUME_NUMBER, _ORDINAL, _YEAR):
        title = pattern.sub(" ", title)
    return normalize_text(title)
