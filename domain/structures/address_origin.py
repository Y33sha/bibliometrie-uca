"""Origine du texte d'une adresse : adresse brute, libellé HAL ou nom seul."""

import re
from collections.abc import Set
from enum import StrEnum

from domain.country_detection import CountryNames
from domain.normalize import normalize_text


class AddressOrigin(StrEnum):
    """Origine du texte d'une adresse."""

    RAW = "raw"
    """Adresse imprimée dans la publication."""
    HAL_LABEL = "hal_label"
    """Libellé d'une structure HAL : « SIGLE - Nom (adresse postale - Pays) », ou « Nom (Pays) »."""
    NAME_ONLY = "name_only"
    """Nom seul d'une structure ou d'un établissement, ou texte étranger à une adresse."""


# Libellé HAL complet : adresse postale et pays entre parenthèses finales, séparés par « - ».
_HAL_LABEL = re.compile(r"\(.* - [^()]+\)$")
_FINAL_PARENTHESES = re.compile(r"\(([^()]+)\)$")


def address_origin(
    raw_text: str,
    normalized_text: str,
    *,
    structure_names: Set[str],
    country_names: CountryNames,
) -> AddressOrigin:
    """Renvoie l'origine du texte d'une adresse. Les règles s'appliquent dans l'ordre : la première applicable décide.

    Args:
        structure_names: noms normalisés des structures HAL et des organisations ROR.
    """
    text = raw_text.strip()
    if _HAL_LABEL.search(text):
        return AddressOrigin.HAL_LABEL
    if normalized_text in structure_names:
        return AddressOrigin.NAME_ONLY
    if "," in text:
        return AddressOrigin.RAW
    final = _FINAL_PARENTHESES.search(text)
    if final and normalize_text(final.group(1)) in country_names.iso_by_form:
        return AddressOrigin.HAL_LABEL
    if country_names.trailing_country(normalized_text):
        return AddressOrigin.RAW
    return AddressOrigin.NAME_ONLY
