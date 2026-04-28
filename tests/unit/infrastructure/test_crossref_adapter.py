"""Garde-fous sur la conformité de l'adapter CrossRef au polite pool.

Le polite pool CrossRef autorise 10 req/s + 3 connexions simultanées max.
Dépasser l'un ou l'autre déclenche des 429 immédiats. Ces tests verrouillent
les constantes pour qu'on ne retombe pas dans le piège (cf. incident où
max_concurrent=5 produisait 429 dès la première vague).
"""

from infrastructure.sources.crossref.fetch_missing_doi import (
    CrossrefFetchMissingDoiAdapter,
)


def test_polite_pool_concurrency_limit():
    assert CrossrefFetchMissingDoiAdapter.max_concurrent <= 3


def test_polite_pool_throughput_cap():
    """Avec sem=3 et latence ~200 ms, request_delay doit être ≥ 0.1 s pour
    plafonner sous 10 req/s sustained."""
    adapter = CrossrefFetchMissingDoiAdapter
    latency_estimate = 0.2
    sustained_rate = adapter.max_concurrent / (adapter.request_delay_s + latency_estimate)
    assert sustained_rate <= 10.0, f"{sustained_rate:.1f} req/s > 10 (polite pool limit)"
