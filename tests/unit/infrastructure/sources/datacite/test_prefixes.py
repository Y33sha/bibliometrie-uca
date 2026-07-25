"""Tests du client `api.datacite.org/prefixes` (`fetch_datacite_prefix`, `_parse_datacite_prefix_payload`).

Mockent `requests.request` (utilisé par `http_request_with_retry`) pour ne pas dépendre du réseau.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import requests

from infrastructure.sources.datacite.prefixes import (
    _parse_datacite_prefix_payload,
    fetch_datacite_prefix,
)


def _mock_response(status_code: int = 200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "x"
    resp.json.return_value = json_data
    return resp


def _datacite_payload(
    prefix: str, client_symbol: str, client_name: str, provider_id: str, provider_name: str
) -> dict:
    """Réponse JSON:API minimaliste, calquée sur api.datacite.org/prefixes/{p}?include=clients,providers."""
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
    """Si `relationships` référence un client mais qu'il manque dans `included`, on rate."""
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


def test_fetch_datacite_prefix_ok(monkeypatch):
    payload = _datacite_payload(
        "10.14758", "inist.inra", "INRAE", "gkjj", "Institut national de recherche"
    )
    monkeypatch.setattr(requests, "request", lambda *a, **kw: _mock_response(200, payload))
    assert fetch_datacite_prefix("10.14758", user_agent="ua") == (
        "Institut national de recherche",
        "INRAE",
        "inist.inra",
    )


def test_fetch_datacite_prefix_http_error_returns_none(monkeypatch):
    def raising(*a, **kw):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(requests, "request", raising)
    assert fetch_datacite_prefix("10.5281", user_agent="ua") is None
