"""Garde-fous sur le débit de l'adapter DataCite.

DataCite n'a pas de polite pool contractuel, mais on reste conservateur pour
ne pas se faire throttler. Ces tests verrouillent les constantes de débit.
"""

from infrastructure.sources.datacite.fetch_missing_doi import (
    DataciteFetchMissingDoiAdapter,
)


def test_concurrency_limit():
    assert DataciteFetchMissingDoiAdapter.max_concurrent <= 3


def test_throughput_cap():
    """Avec sem=3 et latence ~200 ms, le débit sustained reste bien sous 10 req/s."""
    adapter = DataciteFetchMissingDoiAdapter
    latency_estimate = 0.2
    sustained_rate = adapter.max_concurrent / (adapter.request_delay_s + latency_estimate)
    assert sustained_rate <= 10.0, f"{sustained_rate:.1f} req/s trop élevé"
