"""Origine du texte d'une adresse : adresse brute, libellé HAL ou nom seul."""

import re
from collections.abc import Iterable, Set
from dataclasses import dataclass
from enum import StrEnum

from domain.addresses.country_detection import CountryNames
from domain.normalize import normalize_text


class AddressOrigin(StrEnum):
    """Origine du texte d'une adresse."""

    RAW = "raw"
    """Adresse imprimée dans la publication."""
    HAL_LABEL = "hal_label"
    """Libellé d'une structure HAL : « SIGLE - Nom (adresse postale - Pays) », « Nom (Pays) », ou nom précisé entre crochets (« University of Mons [Belgium] »)."""
    NAME_ONLY = "name_only"
    """Nom seul d'une structure ou d'un établissement, suivi ou non du pays, ou texte étranger à une adresse."""


_HAL_LABEL = re.compile(r"\(.* - [^()]+\)$")
"""Libellé HAL complet : adresse postale et pays entre parenthèses finales, séparés par « - »."""
_FINAL_PARENTHESES = re.compile(r"\(([^()]+)\)$")
_BRACKETS = re.compile(r"\[([^\]]*)\]")
_PERIOD = re.compile(r"^\d{4}\s*-\s*(\d{4}|\.\.\.)?$")
"""Période d'un nom HAL : « [2017-2020] », « [2021-...] »."""


@dataclass(frozen=True, slots=True)
class OriginReferentials:
    """Référentiels lus par le classement de l'origine d'une adresse."""

    structure_names: Set[str]
    """Noms normalisés des structures HAL et des organisations ROR."""
    bare_structure_names: Set[str]
    """Mêmes noms, sans leurs précisions entre crochets : « Waseda University [Tokyo] » donne « waseda university »."""
    city_names: Set[str]
    """Formes normalisées des noms de villes."""
    country_names: CountryNames

    @classmethod
    def from_names(
        cls,
        structure_names: Iterable[str],
        *,
        city_names: Iterable[str],
        country_names: CountryNames,
    ) -> OriginReferentials:
        """Construit les référentiels depuis les noms bruts des structures."""
        names = list(structure_names)
        return cls(
            structure_names=frozenset(normalize_text(n) for n in names) - {""},
            bare_structure_names=frozenset(normalize_text(_BRACKETS.sub(" ", n)) for n in names)
            - {""},
            city_names=frozenset(city_names),
            country_names=country_names,
        )

    def is_country(self, normalized: str) -> bool:
        """Vrai si le texte normalisé est un nom de pays."""
        return normalized in self.country_names.iso_by_form

    def is_place(self, normalized: str) -> bool:
        """Vrai si le texte normalisé est un nom de ville ou de pays."""
        return normalized in self.city_names or self.is_country(normalized)


def address_origin(
    raw_text: str, normalized_text: str, referentials: OriginReferentials
) -> AddressOrigin:
    """Renvoie l'origine du texte d'une adresse. Les règles s'appliquent dans l'ordre : la première applicable décide."""
    text = raw_text.strip()
    if _HAL_LABEL.search(text) or any(
        _is_hal_precision(content, referentials) for content in _BRACKETS.findall(text)
    ):
        return AddressOrigin.HAL_LABEL
    if normalized_text in referentials.structure_names or _is_name_and_country(text, referentials):
        return AddressOrigin.NAME_ONLY
    final = _FINAL_PARENTHESES.search(text)
    if final and referentials.is_country(normalize_text(final.group(1))):
        return AddressOrigin.HAL_LABEL
    if "," in text or referentials.country_names.trailing_country(normalized_text):
        return AddressOrigin.RAW
    return AddressOrigin.NAME_ONLY


def _is_hal_precision(content: str, referentials: OriginReferentials) -> bool:
    """Vrai si le contenu de crochets est une précision de nom HAL : période, lieux, ou nom de structure."""
    content = content.strip()
    if _PERIOD.match(content):
        return True
    places = [part for p in content.split(",") if (part := normalize_text(p))]
    if places and all(referentials.is_place(p) for p in places):
        return True
    return normalize_text(content) in referentials.structure_names


def _is_name_and_country(text: str, referentials: OriginReferentials) -> bool:
    """Vrai pour « Nom, Pays » : nom de structure sans ses précisions entre crochets, puis pays, en deux segments."""
    if text.count(",") != 1:
        return False
    name, country = text.split(",")
    return (
        referentials.is_country(normalize_text(country))
        and normalize_text(name) in referentials.bare_structure_names
    )
