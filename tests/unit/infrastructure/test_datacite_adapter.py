"""Garde-fous sur le débit de l'adapter DataCite.

DataCite throttle agressivement les clients non authentifiés (429 en rafale dès
~10 req/s). Ces tests verrouillent un débit conservateur pour ne pas se faire
limiter.
"""

from infrastructure.sources.datacite.fetch_missing_doi import (
    DataciteFetchMissingDoiAdapter,
)


def test_concurrency_serial():
    # Interrogation en série : les bursts concurrents déclenchent des 429.
    assert DataciteFetchMissingDoiAdapter.max_concurrent == 1


def test_throughput_cap():
    """Avec une latence ~200 ms, le débit sustained reste bas (≈ 1-3 req/s)."""
    adapter = DataciteFetchMissingDoiAdapter
    latency_estimate = 0.2
    sustained_rate = adapter.max_concurrent / (adapter.request_delay_s + latency_estimate)
    assert sustained_rate <= 3.0, f"{sustained_rate:.1f} req/s trop élevé pour DataCite"
