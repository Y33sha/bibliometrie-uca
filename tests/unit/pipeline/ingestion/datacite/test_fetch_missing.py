"""Garde-fous sur le débit de la recherche par DOI dans DataCite.

DataCite limite à 1000 requêtes / 5 min pour un client identifié (User-Agent
avec mailto), soit ~3,3 req/s. Ces tests vérifient que le budget de débit
reste sous cette limite.
"""

from pipeline.ingestion.api_params import MAX_PER_SECOND
from pipeline.ingestion.datacite.fetch_missing import DataciteDoiSearch

# Limite identifiée DataCite : 1000 req / 5 min = 300 s.
_DATACITE_MAX_REQ_PER_S = 1000 / 300


def test_concurrency_limit():
    assert DataciteDoiSearch.max_concurrent <= 3


def test_budget_under_the_identified_limit():
    assert MAX_PER_SECOND["datacite"] <= _DATACITE_MAX_REQ_PER_S
