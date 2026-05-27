"""Tests unitaires des méthodes pures de `PgThesesExtractAdapter`.

Couvre le savoir adapter sans I/O : construction de requête (`build_query`)
et parsing des thèses (`extract_id`, `extract_doi`). La plomberie HTTP/SQL
est couverte ailleurs (helper retry + intégration).
"""

from __future__ import annotations

import pytest

from infrastructure.sources.theses.extract_theses import PgThesesExtractAdapter


@pytest.fixture
def adapter() -> PgThesesExtractAdapter:
    return PgThesesExtractAdapter(base_url="https://example/")


class TestBuildQuery:
    def test_ppn(self, adapter):
        assert adapter.build_query(ppn="196200032") == "etabSoutenancePpn:(196200032)"


class TestExtractId:
    def test_returns_nnt_for_defended(self, adapter):
        # Thèse soutenue : NNT préfixé YYYY.
        assert adapter.extract_id({"id": "2021UCFAC022", "nnt": "2021UCFAC022"}) == "2021UCFAC022"

    def test_returns_internal_id_for_ongoing(self, adapter):
        # Thèse en cours : id theses.fr `s...` ; pas de NNT.
        assert adapter.extract_id({"id": "s367812", "nnt": None}) == "s367812"

    def test_empty_when_missing(self, adapter):
        assert adapter.extract_id({}) == ""


class TestExtractDoi:
    def test_returns_stripped_doi(self, adapter):
        assert adapter.extract_doi({"doi": "  10.1000/abc  "}) == "10.1000/abc"

    def test_returns_none_when_absent(self, adapter):
        assert adapter.extract_doi({}) is None

    def test_returns_none_when_empty_string(self, adapter):
        # `doi` présent mais string vide → None.
        assert adapter.extract_doi({"doi": ""}) is None

    def test_returns_none_when_whitespace_only(self, adapter):
        assert adapter.extract_doi({"doi": "   "}) is None

    def test_returns_none_when_not_string(self, adapter):
        # Cas anormal mais à pinner : `doi` non-str → None silencieux.
        assert adapter.extract_doi({"doi": 12345}) is None
