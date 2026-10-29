"""Lecture par lots du type des sources OpenAlex, pour l'enrichissement des revues."""

from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.openalex import serial_enrichment as mod


class TestFetchSourcesBatch:
    def test_maps_short_id_to_type(self, monkeypatch):
        payload = {"results": [{"id": "https://openalex.org/S1", "type": "journal"}]}
        monkeypatch.setattr(mod, "http_request_with_retry", lambda *a, **k: payload)
        out = mod.fetch_sources_batch(["S1"], openalex_sources_api="x")
        assert out == {"S1": "journal"}

    def test_returns_empty_on_failure(self, monkeypatch):
        def boom(*_a, **_k):
            raise SourceUnavailableError("openalex")

        monkeypatch.setattr(mod, "http_request_with_retry", boom)
        out = mod.fetch_sources_batch(["S1"], openalex_sources_api="x")
        assert out == {}
