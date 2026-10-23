"""Garde-fous sur la conformité de la recherche par DOI dans Crossref au polite pool.

Le polite pool Crossref autorise 10 req/s et 3 requêtes simultanées au plus.
Dépasser l'un ou l'autre déclenche des 429 immédiats (max_concurrent=5 en
produisait dès la première vague). Ces tests verrouillent le budget du profil
et la concurrence de la recherche.
"""

from domain.sources.registry import PROFILES, Source
from pipeline.ingestion.crossref.fetch_missing import CrossrefDoiSearch


def test_polite_pool_concurrency_limit():
    assert CrossrefDoiSearch.max_concurrent <= 3


def test_polite_pool_throughput_cap():
    assert PROFILES[Source.CROSSREF].max_per_second <= 10
