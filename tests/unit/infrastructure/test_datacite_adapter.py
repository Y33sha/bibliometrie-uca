"""Garde-fous sur le débit de l'adapter DataCite.

DataCite limite à 1000 requêtes / 5 min pour un client identifié (User-Agent
avec mailto), soit ~3,3 req/s. L'API répond très vite, donc le délai par worker
domine le débit. Ces tests verrouillent un débit sous cette limite.
"""

from infrastructure.sources.datacite.fetch_missing_doi import (
    DataciteFetchMissingDoiAdapter,
)

# Limite identifiée DataCite : 1000 req / 5 min = 300 s.
_DATACITE_MAX_REQ_PER_S = 1000 / 300


def test_concurrency_limit():
    assert DataciteFetchMissingDoiAdapter.max_concurrent <= 3


def test_throughput_cap():
    """L'API répond en ~10 ms : au pire (latence négligeable) le débit sustained
    vaut concurrence / délai et doit rester sous la limite identifiée DataCite."""
    adapter = DataciteFetchMissingDoiAdapter
    sustained_rate = adapter.max_concurrent / adapter.request_delay_s
    assert sustained_rate <= _DATACITE_MAX_REQ_PER_S, (
        f"{sustained_rate:.1f} req/s dépasse la limite DataCite (~3,3 req/s)"
    )
