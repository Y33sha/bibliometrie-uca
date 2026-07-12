"""Adapter OpenAlex Sources → enrichissement des revues : parsing APC et fetch batch."""

from infrastructure.sources.openalex import journal_enrichment as mod


class TestExtractApc:
    def test_prefers_eur(self):
        source = {
            "apc_prices": [{"currency": "USD", "price": 2000}, {"currency": "EUR", "price": 1800}]
        }
        assert mod.extract_apc(source) == (1800, "EUR")

    def test_first_currency_when_no_eur(self):
        assert mod.extract_apc({"apc_prices": [{"currency": "GBP", "price": 1500}]}) == (
            1500,
            "GBP",
        )

    def test_falls_back_to_apc_usd(self):
        assert mod.extract_apc({"apc_usd": 2500}) == (2500, "USD")

    def test_none_when_absent(self):
        assert mod.extract_apc({}) == (None, "EUR")


class TestFetchSourcesBatch:
    def test_parses_results_into_tuples(self, monkeypatch):
        payload = {
            "results": [{"id": "https://openalex.org/S1", "type": "journal", "apc_usd": 1000}]
        }
        monkeypatch.setattr(mod, "http_request_with_retry", lambda *a, **k: payload)
        out = mod.fetch_sources_batch(["S1"], openalex_sources_api="x", api_key=None, mailto="m")
        assert out == {"S1": (1000, "USD", "journal")}

    def test_returns_empty_on_failure(self, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("network down")

        monkeypatch.setattr(mod, "http_request_with_retry", boom)
        out = mod.fetch_sources_batch(["S1"], openalex_sources_api="x", api_key=None, mailto="m")
        assert out == {}
