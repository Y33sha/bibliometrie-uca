"""Pays d'une adresse : moyens de détection et préséance entre les candidats."""

from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum


class CountryDetectionMethod(StrEnum):
    """Moyen qui propose un pays pour une adresse."""

    MANUAL = "manual"
    COUNTRY_NAME = "country_name"
    SOURCE_OPENALEX = "source_openalex"
    INSTITUTION = "institution"
    CITY = "city"
    SOURCE_SCANR = "source_scanr"


# Moyen des pays donnés par une source pour une affiliation, par nom de source.
SOURCE_COUNTRY_METHODS: dict[str, CountryDetectionMethod] = {
    "scanr": CountryDetectionMethod.SOURCE_SCANR,
    "openalex": CountryDetectionMethod.SOURCE_OPENALEX,
}

# Moyens par rang de préséance, d'après une revue à la main des désaccords.
_PRECEDENCE: tuple[CountryDetectionMethod, ...] = (
    CountryDetectionMethod.MANUAL,
    CountryDetectionMethod.COUNTRY_NAME,
    CountryDetectionMethod.SOURCE_OPENALEX,
    CountryDetectionMethod.INSTITUTION,
    CountryDetectionMethod.CITY,
    CountryDetectionMethod.SOURCE_SCANR,
)

# Nombre de moyens qui, d'accord sur un autre pays, l'emportent sur le premier moyen.
_CONTRARY_QUORUM = 2


def retained_countries(
    candidates: Mapping[CountryDetectionMethod, Iterable[str]],
) -> frozenset[str]:
    """Renvoie les pays retenus d'une adresse, d'après les candidats de chaque moyen.

    Le premier moyen qui propose un pays l'emporte. `manual` l'emporte toujours. Un autre premier moyen cède quand deux autres moyens proposent un même autre pays et qu'aucun ne soutient le sien.
    """
    proposals = [frozenset(candidates.get(method, ())) for method in _PRECEDENCE]
    first = next((rank for rank, codes in enumerate(proposals) if codes), None)
    if first is None:
        return frozenset()
    chosen = proposals[first]
    if first == 0:
        return chosen
    others = Counter(
        code for rank, codes in enumerate(proposals) if rank != first for code in codes
    )
    if chosen & others.keys():
        return chosen
    contrary = frozenset(code for code, n in others.items() if n >= _CONTRARY_QUORUM)
    return contrary or chosen
