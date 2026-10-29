"""Conformité de la recherche par DOI dans Crossref aux limites du polite pool.

Le polite pool Crossref autorise au plus 10 requêtes par seconde et 3 requêtes simultanées. Au-delà, Crossref répond 429.
"""

from pipeline.ingestion.api_params import MAX_PER_SECOND
from pipeline.ingestion.crossref.fetch_missing import CrossrefDoiSearch


def test_polite_pool_concurrency_limit():
    assert CrossrefDoiSearch.max_concurrent <= 3


def test_polite_pool_throughput_cap():
    assert MAX_PER_SECOND["crossref"] <= 10
