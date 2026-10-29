"""Débit de la recherche par DOI dans DataCite.

DataCite accepte 1000 requêtes en 5 minutes d'un client identifié (`mailto` dans le User-Agent), soit environ 3,3 requêtes par seconde. Le débit de la recherche reste sous cette limite.
"""

from pipeline.ingestion.api_params import MAX_PER_SECOND
from pipeline.ingestion.datacite.fetch_missing import DataciteDoiSearch

# Limite DataCite d'un client identifié : 1000 requêtes en 300 s.
_DATACITE_MAX_REQ_PER_S = 1000 / 300


def test_concurrency_limit():
    assert DataciteDoiSearch.max_concurrent <= 3


def test_budget_under_the_identified_limit():
    assert MAX_PER_SECOND["datacite"] <= _DATACITE_MAX_REQ_PER_S
