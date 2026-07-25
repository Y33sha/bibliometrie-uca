"""Tests du client `doi.org/ra` (`resolve_ra`).

Mockent `requests.request` (utilisé par `http_request_with_retry`) pour ne pas dépendre du réseau.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import requests

from infrastructure.sources.doi_org.registration_agency import resolve_ra


def _mock_response(status_code: int = 200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "x"
    resp.json.return_value = json_data
    return resp


def test_resolve_ra_crossref(monkeypatch):
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **kw: _mock_response(200, [{"DOI": "10.1038/x", "RA": "Crossref"}]),
    )
    assert resolve_ra("10.1038/x", user_agent="ua") == "Crossref"


def test_resolve_ra_datacite(monkeypatch):
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **kw: _mock_response(200, [{"DOI": "10.5281/x", "RA": "DataCite"}]),
    )
    assert resolve_ra("10.5281/x", user_agent="ua") == "DataCite"


def test_resolve_ra_unknown_is_valid(monkeypatch):
    """`unknown` est une valeur valide renvoyée par doi.org — pas un échec."""
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **kw: _mock_response(200, [{"DOI": "10.9999/x", "RA": "unknown"}]),
    )
    assert resolve_ra("10.9999/x", user_agent="ua") == "unknown"


def test_resolve_ra_doi_not_found_returns_none(monkeypatch):
    """`'DOI Not Found'` = DOI inexistant → caller doit retenter un autre DOI."""
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **kw: _mock_response(200, [{"DOI": "10.x/foo", "RA": "DOI Not Found"}]),
    )
    assert resolve_ra("10.x/foo", user_agent="ua") is None


def test_resolve_ra_http_error_returns_none(monkeypatch):
    def raising(*a, **kw):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(requests, "request", raising)
    assert resolve_ra("10.1038/x", user_agent="ua") is None


def test_resolve_ra_empty_payload_returns_none(monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **kw: _mock_response(200, []))
    assert resolve_ra("10.1038/x", user_agent="ua") is None
