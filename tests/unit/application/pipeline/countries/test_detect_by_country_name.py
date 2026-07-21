"""Tests unitaires du matching d'un nom de pays en fin d'adresse normalisée."""

from application.pipeline.countries.detect_by_country_name import _match_trailing_country

FORMS = {
    "france": "fr",
    "kingdom": "xx",  # piège : sous-chaîne de "united kingdom"
    "united kingdom": "gb",
    "new zealand": "nz",
}
MAX_TOKENS = 2  # plus long nom du référentiel : « united kingdom » / « new zealand »


def test_matches_single_token_at_end():
    assert _match_trailing_country("cnrs paris france", FORMS, MAX_TOKENS) == "fr"


def test_matches_without_comma():
    # Cas rattrapé par le suffixe : pays collé sans virgule.
    assert _match_trailing_country("department of physics france", FORMS, MAX_TOKENS) == "fr"


def test_longest_form_wins():
    # « united kingdom » (2 tokens) prime sur le piège « kingdom ».
    assert _match_trailing_country("some lab london united kingdom", FORMS, MAX_TOKENS) == "gb"


def test_whole_text_is_a_country():
    assert _match_trailing_country("new zealand", FORMS, MAX_TOKENS) == "nz"


def test_country_name_not_at_end_is_ignored():
    assert _match_trailing_country("france avenue de paris", FORMS, MAX_TOKENS) is None


def test_empty_text():
    assert _match_trailing_country("", FORMS, MAX_TOKENS) is None
