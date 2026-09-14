"""Tests de `language_code` : valeur d'une source → code du référentiel des langues."""

import pytest

from domain.source_publications.languages import language_code

_FORMS = {"en": "en", "eng": "en", "english": "en", "fr": "fr", "fra": "fr", "fre": "fr"}


@pytest.mark.parametrize(
    ("raw", "code"),
    [("en", "en"), ("eng", "en"), ("English", "en"), (" FRE ", "fr"), ("fra", "fr")],
)
def test_known_form_gives_its_code(raw: str, code: str):
    assert language_code(raw, _FORMS) == code


@pytest.mark.parametrize("raw", ["und", "qno", "", None])
def test_unknown_or_absent_value_gives_none(raw: str | None):
    assert language_code(raw, _FORMS) is None
