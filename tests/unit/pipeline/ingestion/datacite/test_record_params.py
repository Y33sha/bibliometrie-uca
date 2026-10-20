"""Toute requête DataCite qui rapatrie des enregistrements demande les affiliations en objets (`affiliation=true`)."""

import asyncio

import httpx2

from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.datacite.api import DataciteClient
from pipeline.ingestion.datacite.fetch_missing import DataciteDoiSearch
from pipeline.ingestion.datacite.fetch_stale import DataciteStaleRefetch

_DOIS = "https://api.datacite.org/dois"
_EMPTY = {"data": [], "links": {}, "meta": {"total": 0}}


def _affiliation_param(route):
    return [call.url.params.get("affiliation") for call in route.calls]


def test_extraction(http_mock):
    route = http_mock.get(_DOIS).mock(return_value=httpx2.Response(200, json=_EMPTY))
    client = DataciteClient(API_BASE_URLS["datacite"])
    client.count("publicationYear:2024", "2024")
    client.fetch_page("publicationYear:2024", None, "2024")
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
