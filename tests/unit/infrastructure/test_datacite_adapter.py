"""Garde-fous sur le débit de l'adapter DataCite.

Limite DataCite (anonyme) : 3000 req / 5 min = 10 req/s. L'API répond très vite,
donc le délai par worker domine le débit. Ces tests verrouillent un débit sous
la limite.
"""

from infrastructure.sources.datacite.fetch_missing_doi import (
    DataciteFetchMissingDoiAdapter,
)


def test_concurrency_limit():
    assert DataciteFetchMissingDoiAdapter.max_concurrent <= 3


def test_throughput_cap():
    """L'API répond en ~10 ms : au pire (latence négligeable) le débit sustained
    vaut concurrence / délai et doit rester sous la limite DataCite de 10 req/s."""
    adapter = DataciteFetchMissingDoiAdapter
    sustained_rate = adapter.max_concurrent / adapter.request_delay_s
    assert sustained_rate <= 10.0, f"{sustained_rate:.1f} req/s dépasse la limite DataCite"
