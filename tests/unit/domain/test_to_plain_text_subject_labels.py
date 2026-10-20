"""`to_plain_text` appliqué aux libellés de sujet : casse et accents préservés, espaces réduits, balisage retiré."""

from domain.normalize import to_plain_text


class TestSubjectLabel:
    def test_strips_outer_whitespace(self):
        assert to_plain_text("  machine learning  ") == "machine learning"

    def test_collapses_internal_whitespace(self):
        assert to_plain_text("machine    learning") == "machine learning"

    def test_handles_tabs_and_newlines(self):
        assert to_plain_text("machine\tlearning\n") == "machine learning"

    def test_preserves_case_and_accents(self):
        assert to_plain_text("Apprentissage Profond") == "Apprentissage Profond"
        assert to_plain_text("écologie microbienne") == "écologie microbienne"

    def test_empty_string(self):
        assert to_plain_text("") == ""

    def test_strips_markup_deposited_by_sources(self):
        # Relevé en base : les noms d'espèces arrivent en italique depuis les sources.
        assert to_plain_text("<italic>Corynebacterium bovis</italic>") == ("Corynebacterium bovis")
        assert to_plain_text(
            "<italic>Pseudomonas syringae</italic> pv. <italic>tomato</italic>"
        ) == ("Pseudomonas syringae pv. tomato")
