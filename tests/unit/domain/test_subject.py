"""Tests du helper de `domain/subjects/subject.py`."""

from domain.subjects.subject import normalize_label


class TestNormalizeLabel:
    def test_strips_outer_whitespace(self):
        assert normalize_label("  machine learning  ") == "machine learning"

    def test_collapses_internal_whitespace(self):
        assert normalize_label("machine    learning") == "machine learning"

    def test_handles_tabs_and_newlines(self):
        assert normalize_label("machine\tlearning\n") == "machine learning"

    def test_preserves_case_and_accents(self):
        assert normalize_label("Apprentissage Profond") == "Apprentissage Profond"
        assert normalize_label("écologie microbienne") == "écologie microbienne"

    def test_empty_string(self):
        assert normalize_label("") == ""
