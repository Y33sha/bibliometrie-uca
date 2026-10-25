"""Garde-fous sur la conformité de la recherche par DOI dans Crossref au polite pool.

Le polite pool Crossref autorise 10 req/s et 3 requêtes simultanées au plus.
Dépasser l'un ou l'autre déclenche des 429 immédiats (max_concurrent=5 en
produisait dès la première vague). Ces tests verrouillent le budget de débit
et la concurrence de la recherche.
"""

from pipeline.ingestion.api_params import MAX_PER_SECOND
from pipeline.ingestion.crossref.fetch_missing import CrossrefDoiSearch


def test_polite_pool_concurrency_limit():
    assert CrossrefDoiSearch.max_concurrent <= 3


def test_polite_pool_throughput_cap():
    assert MAX_PER_SECOND["crossref"] <= 10
