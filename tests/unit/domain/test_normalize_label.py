"""Tests unitaires de `domain.normalize.normalize_label`."""

from domain.normalize import normalize_label


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

    def test_strips_markup_deposited_by_sources(self):
        # Relevé en base : les noms d'espèces arrivent en italique depuis les sources.
        assert normalize_label("<italic>Corynebacterium bovis</italic>") == (
            "Corynebacterium bovis"
        )
        assert normalize_label(
            "<italic>Pseudomonas syringae</italic> pv. <italic>tomato</italic>"
        ) == ("Pseudomonas syringae pv. tomato")
