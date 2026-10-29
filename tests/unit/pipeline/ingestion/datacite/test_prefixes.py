"""Tests du client `api.datacite.org/prefixes` (`fetch_datacite_prefix`, `_parse_datacite_prefix_payload`).

Les requêtes HTTP passent par la fixture `http_mock`.
"""

from __future__ import annotations

import httpx2
import pytest

from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE
from pipeline.ingestion.datacite.prefixes import (
    _parse_datacite_prefix_payload,
    fetch_datacite_prefix,
)


def _datacite_payload(
    prefix: str, client_symbol: str, client_name: str, provider_id: str, provider_name: str
) -> dict:
    """Réponse JSON:API minimale, sur le modèle de api.datacite.org/prefixes/{p}?include=clients,providers."""
    return {
        "data": {
            "id": prefix,
            "type": "prefixes",
            "attributes": {"prefix": prefix},
            "relationships": {
                "clients": {"data": [{"id": client_symbol, "type": "clients"}]},
                "providers": {"data": [{"id": provider_id, "type": "providers"}]},
            },
        },
        "included": [
            {
                "id": client_symbol,
                "type": "clients",
                "attributes": {"name": client_name, "clientType": "repository"},
            },
            {
                "id": provider_id,
                "type": "providers",
                "attributes": {"name": provider_name},
            },
        ],
    }


def test_parse_datacite_prefix_payload_ok():
    payload = _datacite_payload(
        "10.5281",
        "cern.zenodo",
        "Zenodo",
        "cern",
        "CERN - European Organization for Nuclear Research",
    )
    assert _parse_datacite_prefix_payload(payload) == (
        "CERN - European Organization for Nuclear Research",
        "Zenodo",
        "cern.zenodo",
    )


def test_parse_datacite_prefix_payload_missing_relationships_returns_none():
    payload = {"data": {"id": "10.5281", "type": "prefixes", "relationships": {}}, "included": []}
    assert _parse_datacite_prefix_payload(payload) is None


def test_parse_datacite_prefix_payload_missing_included_entry_returns_none():
    """Un client référencé dans `relationships` et absent de `included` donne None."""
    payload = {
        "data": {
            "relationships": {
                "clients": {"data": [{"id": "xxx", "type": "clients"}]},
                "providers": {"data": [{"id": "yyy", "type": "providers"}]},
            },
        },
        "included": [],
    }
    assert _parse_datacite_prefix_payload(payload) is None


def test_parse_datacite_prefix_payload_non_dict_returns_none():
    assert _parse_datacite_prefix_payload(None) is None
    assert _parse_datacite_prefix_payload([]) is None
    assert _parse_datacite_prefix_payload("nope") is None


async def _fetch(prefix: str):
    async with httpx2.AsyncClient() as client:
        return await fetch_datacite_prefix(client, prefix)


@pytest.mark.asyncio
async def test_fetch_datacite_prefix_ok(http_mock):
    payload = _datacite_payload(
        "10.14758", "inist.inra", "INRAE", "gkjj", "Institut national de recherche"
    )
    http_mock.get("https://api.datacite.org/prefixes/10.14758").mock(
        return_value=httpx2.Response(200, json=payload)
    )
    assert await _fetch("10.14758") == ("Institut national de recherche", "INRAE", "inist.inra")


@pytest.mark.asyncio
async def test_fetch_datacite_prefix_404_is_not_found(http_mock):
    http_mock.get("https://api.datacite.org/prefixes/10.5281").mock(
        return_value=httpx2.Response(404)
    )
    assert await _fetch("10.5281") is NOT_FOUND


@pytest.mark.asyncio
async def test_fetch_datacite_prefix_400_is_not_found(http_mock):
    """DataCite répond 400 à chaque appel pour un préfixe dont il n'a qu'un enregistrement Handle (10.1713)."""
    http_mock.get("https://api.datacite.org/prefixes/10.1713").mock(
        return_value=httpx2.Response(
            400, json={"errors": [{"status": "400", "title": "undefined method 'uid'"}]}
        )
    )
    assert await _fetch("10.1713") is NOT_FOUND


@pytest.mark.asyncio
async def test_fetch_datacite_prefix_network_error_is_unavailable(http_mock):
    http_mock.get("https://api.datacite.org/prefixes/10.5281").mock(
        side_effect=httpx2.ConnectError("boom")
    )
    assert await _fetch("10.5281") is UNAVAILABLE
