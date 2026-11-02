"""Tests des formes de nom courtes d'une structure."""

from domain.structures.name_forms import SHORT_FORM_MAX_LENGTH, is_short_form


class TestIsShortForm:
    def test_longest_short_form(self) -> None:
        assert is_short_form("a" * SHORT_FORM_MAX_LENGTH)

    def test_one_character_more(self) -> None:
        assert not is_short_form("a" * (SHORT_FORM_MAX_LENGTH + 1))
