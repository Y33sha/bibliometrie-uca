"""Tests unitaires de `infrastructure/sources/openalex/parsing.py`."""

from __future__ import annotations

from infrastructure.sources.openalex.parsing import extract_doi, extract_openalex_id


class TestExtractOpenalexId:
    def test_strips_url_prefix(self):
        assert extract_openalex_id({"id": "https://openalex.org/W2741809807"}) == "W2741809807"

    def test_no_prefix_unchanged(self):
        # `str.replace` ne fait rien si la sous-chaîne est absente — pas
        # d'erreur, on retombe sur l'id tel quel.
        assert extract_openalex_id({"id": "W2741809807"}) == "W2741809807"


class TestExtractDoi:
    def test_strips_url_prefix(self):
        assert extract_doi({"doi": "https://doi.org/10.1000/abc"}) == "10.1000/abc"

    def test_bare_doi(self):
        assert extract_doi({"doi": "10.1000/abc"}) == "10.1000/abc"

    def test_none_when_absent(self):
        assert extract_doi({}) is None

    def test_none_when_explicit_none(self):
        assert extract_doi({"doi": None}) is None
