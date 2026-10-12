"""Toute requête DataCite qui rapatrie des enregistrements demande les affiliations en objets (`affiliation=true`)."""

import asyncio

import httpx2
import pytest

from pipeline.sources.api_params import API_BASE_URLS
from pipeline.sources.datacite import fields
from pipeline.sources.datacite.fetch_missing import DataciteDoiSearch
from pipeline.sources.datacite.fetch_stale import DataciteStaleRefetch
from pipeline.sources.datacite.harvest import DataciteClient

_DOIS = "https://api.datacite.org/dois"
_EMPTY = {"data": [], "links": {}, "meta": {"total": 0}}


@pytest.fixture(autouse=True)
def _polite_pool(monkeypatch):
    monkeypatch.setattr(fields, "get_polite_pool_email", lambda: "test@example.org")


def _affiliation_param(route):
    return [call.url.params.get("affiliation") for call in route.calls]


def test_extraction(http_mock):
    route = http_mock.get(_DOIS).mock(return_value=httpx2.Response(200, json=_EMPTY))
    client = DataciteClient(API_BASE_URLS["datacite"])
    client.count(2024, ["Clermont"])
    client.fetch_page(2024, ["Clermont"], None)
    assert _affiliation_param(route) == ["true", "true"]


def test_fetch_missing(http_mock):
    route = http_mock.get(_DOIS).mock(return_value=httpx2.Response(200, json=_EMPTY))
    adapter = DataciteDoiSearch()

    async def fetch():
        async with httpx2.AsyncClient() as client:
            await adapter.fetch_async(client, ["10.1/a"])

    asyncio.run(fetch())
    assert _affiliation_param(route) == ["true"]


def test_fetch_stale(http_mock):
    route = http_mock.get(f"{_DOIS}/10.1/a").mock(
        return_value=httpx2.Response(200, json={"data": {"id": "10.1/a"}})
    )
    adapter = DataciteStaleRefetch()

    async def fetch():
        async with httpx2.AsyncClient() as client:
            await adapter.fetch_by_native_id(client, "10.1/a")

    asyncio.run(fetch())
    assert _affiliation_param(route) == ["true"]
