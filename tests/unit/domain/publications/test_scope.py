"""Tests des constantes de scope publications."""

from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES


class TestOutOfScopeDocTypes:
    def test_contains_known_excluded_types(self):
        assert "memoir" in OUT_OF_SCOPE_DOC_TYPES
        assert "peer_review" in OUT_OF_SCOPE_DOC_TYPES

    def test_excludes_active_types(self):
        for active in ("article", "thesis", "book", "preprint", "ongoing_thesis"):
            assert active not in OUT_OF_SCOPE_DOC_TYPES

    def test_is_frozenset(self):
        """Immuable pour éviter les modifications accidentelles."""
        assert isinstance(OUT_OF_SCOPE_DOC_TYPES, frozenset)
