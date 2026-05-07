from domain.sources.theses import (
    derive_theses_doc_type,
    thesis_authors_compatible,
)


class TestThesisAuthorsCompatible:
    """Variations d'ordre / particules acceptées, mauvais nom rejeté."""

    def test_exact_match(self):
        assert thesis_authors_compatible(("Dupont", "Jean"), ("dupont", "jean")) is True

    def test_no_primary_author_accepts(self):
        """Pas d'auteur connu en BDD → on accepte (titre+année font foi)."""
        assert thesis_authors_compatible(None, ("dupont", "jean")) is True

    def test_empty_primary_last_name_accepts(self):
        assert thesis_authors_compatible(("", ""), ("dupont", "jean")) is True

    def test_incompatible_names(self):
        assert thesis_authors_compatible(("Martin", "Paul"), ("dupont", "jean")) is False

    def test_token_fallback_particule(self):
        """Gère les particules (Ben, Le…) via set des tokens identiques."""
        assert thesis_authors_compatible(("Ben Ali", "Mohammed"), ("mohammed", "ben ali")) is True


class TestDeriveThesesDocType:
    def test_with_date_soutenance_returns_thesis(self):
        assert derive_theses_doc_type("2023-05-10") == "thesis"
        assert derive_theses_doc_type("01/06/2024") == "thesis"

    def test_without_date_soutenance_returns_ongoing_thesis(self):
        assert derive_theses_doc_type(None) == "ongoing_thesis"
        assert derive_theses_doc_type("") == "ongoing_thesis"
