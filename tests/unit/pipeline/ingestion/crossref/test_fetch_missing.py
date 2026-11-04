"""Conformité de la recherche par DOI dans Crossref aux limites du polite pool.

Le polite pool Crossref autorise au plus 10 requêtes par seconde et 3 requêtes simultanées. Au-delà, Crossref répond 429.
"""

from pipeline.ingestion.api_params import MAX_CONCURRENT, MAX_PER_SECOND


def test_polite_pool_concurrency_limit():
    assert MAX_CONCURRENT["crossref"] <= 3


def test_polite_pool_throughput_cap():
    assert MAX_PER_SECOND["crossref"] <= 10
