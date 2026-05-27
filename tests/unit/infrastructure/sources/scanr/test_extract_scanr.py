"""Tests unitaires des méthodes pures de `PgScanrExtractAdapter`.

Couvre le savoir adapter sans I/O : construction de requête Elasticsearch
(`build_query`) et parsing des hits (`extract_id`, `extract_doi`). La
plomberie HTTP/SQL est couverte ailleurs (helper retry + intégration).
"""

from __future__ import annotations

import pytest

from infrastructure.sources.api_limits import SCANR_PER_PAGE
from infrastructure.sources.scanr.extract_scanr import PgScanrExtractAdapter


@pytest.fixture
def adapter() -> PgScanrExtractAdapter:
    return PgScanrExtractAdapter(base_url="https://example/", credentials=("user", "pass"))


class TestBuildQuery:
    def test_basic_shape(self, adapter):
        q = adapter.build_query(year=2024, affiliation_ids=["A1", "A2"])
        assert q["size"] == SCANR_PER_PAGE
        assert q["track_total_hits"] is True
        assert q["query"]["bool"]["must"] == [{"term": {"year": 2024}}]
        assert q["query"]["bool"]["should"] == [
            {"term": {"affiliations.id.keyword": "A1"}},
            {"term": {"affiliations.id.keyword": "A2"}},
        ]
        assert q["query"]["bool"]["minimum_should_match"] == 1
        assert q["sort"] == [{"id.keyword": "asc"}]

    def test_no_affiliations_empty_should(self, adapter):
        # Cas dégénéré : aucune affiliation → should vide. ElasticSearch
        # ne ramènera rien avec `minimum_should_match: 1`. Pinné pour ne
        # pas régresser silencieusement.
        q = adapter.build_query(year=2024, affiliation_ids=[])
        assert q["query"]["bool"]["should"] == []

    def test_search_after_added_when_provided(self, adapter):
        q = adapter.build_query(year=2024, affiliation_ids=["A1"], search_after=["last-id-123"])
        assert q["search_after"] == ["last-id-123"]

    def test_search_after_absent_by_default(self, adapter):
        # Première page : pas de `search_after` dans la requête.
        q = adapter.build_query(year=2024, affiliation_ids=["A1"])
        assert "search_after" not in q


class TestExtractId:
    def test_returns_id_field(self, adapter):
        assert adapter.extract_id({"id": "doi10.1000/abc"}) == "doi10.1000/abc"

    def test_returns_empty_when_missing(self, adapter):
        assert adapter.extract_id({}) == ""


class TestExtractDoi:
    def test_finds_doi_in_external_ids(self, adapter):
        doc = {
            "externalIds": [
                {"type": "hal", "id": "hal-123"},
                {"type": "doi", "id": "10.1000/abc"},
            ]
        }
        assert adapter.extract_doi(doc) == "10.1000/abc"

    def test_returns_first_doi(self, adapter):
        # Plusieurs DOI listés : on ne garde que le premier rencontré.
        doc = {
            "externalIds": [
                {"type": "doi", "id": "10.1000/first"},
                {"type": "doi", "id": "10.1000/second"},
            ]
        }
        assert adapter.extract_doi(doc) == "10.1000/first"

    def test_returns_none_when_no_doi(self, adapter):
        doc = {"externalIds": [{"type": "hal", "id": "hal-123"}]}
        assert adapter.extract_doi(doc) is None

    def test_returns_none_when_external_ids_absent(self, adapter):
        assert adapter.extract_doi({}) is None

    def test_returns_none_when_external_ids_none(self, adapter):
        # `doc.get("externalIds") or []` doit accepter `externalIds: None`
        # sans planter (cas vu sur certaines réponses ScanR).
        assert adapter.extract_doi({"externalIds": None}) is None

    def test_cleans_doi_url_prefix(self, adapter):
        doc = {"externalIds": [{"type": "doi", "id": "https://doi.org/10.1000/abc"}]}
        assert adapter.extract_doi(doc) == "10.1000/abc"
