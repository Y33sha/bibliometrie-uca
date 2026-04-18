"""Tests pour extraction/common.py — fonctions partagées d'extraction."""

import pytest

from extraction.common import compute_hash, get_existing_ids
from domain.publication import clean_doi

# ── compute_hash ─────────────────────────────────────────────────


class TestComputeHash:
    def test_deterministic(self):
        data = {"title": "Test", "year": 2024}
        assert compute_hash(data) == compute_hash(data)

    def test_key_order_independent(self):
        """Le hash ne dépend pas de l'ordre des clés."""
        a = {"z": 1, "a": 2}
        b = {"a": 2, "z": 1}
        assert compute_hash(a) == compute_hash(b)

    def test_different_data_different_hash(self):
        a = {"title": "Foo"}
        b = {"title": "Bar"}
        assert compute_hash(a) != compute_hash(b)

    def test_unicode(self):
        """Les caractères accentués sont gérés correctement."""
        data = {"title": "Étude des phénomènes"}
        h = compute_hash(data)
        assert isinstance(h, str) and len(h) == 32

    def test_nested_structures(self):
        data = {"authors": [{"name": "Dupont"}, {"name": "Durand"}]}
        h = compute_hash(data)
        assert isinstance(h, str) and len(h) == 32

    def test_empty_dict(self):
        assert compute_hash({}) == compute_hash({})


# ── clean_doi ────────────────────────────────────────────────────


class TestCleanDoi:
    def test_none(self):
        assert clean_doi(None) is None

    def test_empty(self):
        assert clean_doi("") is None

    def test_whitespace_only(self):
        assert clean_doi("   ") is None

    def test_plain_doi(self):
        assert clean_doi("10.1234/test.5678") == "10.1234/test.5678"

    def test_https_prefix(self):
        assert clean_doi("https://doi.org/10.1234/test") == "10.1234/test"

    def test_http_prefix(self):
        assert clean_doi("http://doi.org/10.1234/test") == "10.1234/test"

    def test_dx_prefix(self):
        assert clean_doi("https://dx.doi.org/10.1234/test") == "10.1234/test"

    def test_strips_whitespace(self):
        assert clean_doi("  https://doi.org/10.1234/test  ") == "10.1234/test"

    def test_case_insensitive_prefix(self):
        assert clean_doi("HTTPS://DOI.ORG/10.1234/test") == "10.1234/test"


# ── get_existing_ids ─────────────────────────────────────────────


class TestGetExistingIds:
    def test_rejects_unknown_source(self):
        with pytest.raises(ValueError, match="Source inconnue"):
            get_existing_ids(None, "unknown")

    def test_returns_set(self, db):
        """Avec une base vide, retourne un set vide."""
        conn = db.connection
        result = get_existing_ids(conn, "hal")
        assert result == set()
