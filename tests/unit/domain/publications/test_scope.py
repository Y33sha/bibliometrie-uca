"""Tests des constantes de scope publications."""

from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES, OUT_OF_SCOPE_DOC_TYPES_SQL


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


class TestOutOfScopeDocTypesSql:
    def test_format(self):
        """Liste SQL triée alphabétiquement entre apostrophes."""
        assert OUT_OF_SCOPE_DOC_TYPES_SQL == "('memoir', 'peer_review')"

    def test_deterministic_order(self):
        """L'ordre alphabétique garantit un diff déterministe quand on
        recompose la chaîne — utile pour les snapshots et les revues."""
        # Deux appels successifs au sorted produisent la même chaîne.
        sql_again = "(" + ", ".join(f"'{t}'" for t in sorted(OUT_OF_SCOPE_DOC_TYPES)) + ")"
        assert OUT_OF_SCOPE_DOC_TYPES_SQL == sql_again
