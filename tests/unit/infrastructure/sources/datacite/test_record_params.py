"""Toute requête DataCite qui rapatrie des enregistrements demande les affiliations en objets (`affiliation=true`)."""

import asyncio

import httpx2
import pytest

from infrastructure.sources.datacite import nodes
from infrastructure.sources.datacite.extract_datacite import PgDataciteExtractAdapter
from infrastructure.sources.datacite.fetch_missing_doi import DataciteFetchMissingDoiAdapter
from infrastructure.sources.datacite.fetch_stale import DataciteFetchStaleAdapter

_DOIS = "https://api.datacite.org/dois"
_EMPTY = {"data": [], "links": {}, "meta": {"total": 0}}


@pytest.fixture(autouse=True)
def _polite_pool(monkeypatch):
    monkeypatch.setattr(nodes, "get_polite_pool_email", lambda: "test@example.org")


def _affiliation_param(route):
    return [call.url.params.get("affiliation") for call in route.calls]


def test_extraction(http_mock):
    route = http_mock.get(_DOIS).mock(return_value=httpx2.Response(200, json=_EMPTY))
    adapter = PgDataciteExtractAdapter()
    adapter.count(2024, ["Clermont"])
    adapter.fetch_page(2024, ["Clermont"], None)
    assert _affiliation_param(route) == ["true", "true"]


def test_fetch_missing(http_mock):
    route = http_mock.get(_DOIS).mock(return_value=httpx2.Response(200, json=_EMPTY))
    adapter = DataciteFetchMissingDoiAdapter()
    adapter.configure(None)

    async def fetch():
        async with httpx2.AsyncClient() as client:
            await adapter.fetch_async(client, ["10.1/a"])

    asyncio.run(fetch())
    assert _affiliation_param(route) == ["true"]


def test_fetch_stale(http_mock):
    route = http_mock.get(f"{_DOIS}/10.1/a").mock(
        return_value=httpx2.Response(200, json={"data": {"id": "10.1/a"}})
    )
    adapter = DataciteFetchStaleAdapter()
    adapter.configure(None)

    async def fetch():
        async with httpx2.AsyncClient() as client:
            await adapter.fetch_by_native_id(client, "10.1/a")

    asyncio.run(fetch())
    assert _affiliation_param(route) == ["true"]
