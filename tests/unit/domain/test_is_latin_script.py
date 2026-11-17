"""Tests unitaires de `domain.normalize.is_latin_script`."""

from __future__ import annotations

import unicodedata

import pytest

from domain.normalize import is_latin_script


@pytest.mark.parametrize(
    "text",
    [
        "Dougé, Aurore",
        unicodedata.normalize("NFD", "Méité, Méké"),
        "Jevđović, Tanja",
        "DOUGÉ AURORE [FR]",
        "O'Brien-Smith",
        "",
    ],
)
def test_ecriture_latine(text):
    assert is_latin_script(text)


@pytest.mark.parametrize(
    "text",
    ["A·布鲁哈特", "ドゥージェ，オーロル", "두제 오로르", "Станчева, Румяна", "Dougé 道格"],
)
def test_autre_ecriture(text):
    assert not is_latin_script(text)
