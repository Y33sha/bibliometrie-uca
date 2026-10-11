"""Garde-fous sur le débit de la recherche par DOI dans DataCite.

DataCite limite à 1000 requêtes / 5 min pour un client identifié (User-Agent
avec mailto), soit ~3,3 req/s. On vise pile cette limite, sans marge : un 429 +
coupe-circuit ponctuel est rattrapé au run suivant. Ces tests vérifient qu'on
cible bien la limite (ni sous-bridé, ni largement au-dessus).
"""

from pipeline.sources.datacite.fetch_missing import DataciteDoiSearch

# Limite identifiée DataCite : 1000 req / 5 min = 300 s.
_DATACITE_MAX_REQ_PER_S = 1000 / 300


def test_concurrency_limit():
    assert DataciteDoiSearch.max_concurrent <= 3


def test_throughput_targets_limit():
    """Au pire (latence négligeable) le débit vaut concurrence / délai. On vise la
    limite identifiée DataCite (~3,3 req/s), sans la dépasser franchement ni se brider."""
    adapter = DataciteDoiSearch
    sustained_rate = adapter.max_concurrent / adapter.request_delay_s
    assert 3.0 <= sustained_rate <= _DATACITE_MAX_REQ_PER_S + 0.05, (
        f"{sustained_rate:.2f} req/s — viser ~3,3 (limite identifiée DataCite)"
    )
