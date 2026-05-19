"""Tests des clients `doi.org/ra` + `api.crossref.org/prefixes`.

Mockent `requests.request` (utilisé par `http_request_with_retry`) pour
ne pas dépendre du réseau.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import requests

from infrastructure.sources.doi_prefixes.clients import (
    build_user_agent,
    fetch_crossref_prefix,
    parse_member_id,
    resolve_ra,
)

# ── parse_member_id ─────────────────────────────────────────────────


def test_parse_member_id_from_url():
    assert parse_member_id("https://id.crossref.org/member/10") == 10
    assert parse_member_id("https://id.crossref.org/member/297") == 297


def test_parse_member_id_from_int():
    assert parse_member_id(42) == 42


def test_parse_member_id_none_inputs():
    assert parse_member_id(None) is None
    assert parse_member_id("") is None
    assert parse_member_id("not a url") is None


# ── resolve_ra ──────────────────────────────────────────────────────


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


# ── fetch_crossref_prefix ───────────────────────────────────────────


def test_fetch_crossref_prefix_ok(monkeypatch):
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **kw: _mock_response(
            200,
            {
                "message": {
                    "name": "Nature Publishing Group",
                    "member": "https://id.crossref.org/member/297",
                }
            },
        ),
    )
    assert fetch_crossref_prefix("10.1038", user_agent="ua") == (
        "Nature Publishing Group",
        297,
    )


def test_fetch_crossref_prefix_no_member(monkeypatch):
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **kw: _mock_response(200, {"message": {"name": "Foo"}}),
    )
    assert fetch_crossref_prefix("10.1234", user_agent="ua") == ("Foo", None)


def test_fetch_crossref_prefix_missing_name_returns_none(monkeypatch):
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **kw: _mock_response(200, {"message": {}}),
    )
    assert fetch_crossref_prefix("10.1234", user_agent="ua") is None


def test_fetch_crossref_prefix_http_error_returns_none(monkeypatch):
    def raising(*a, **kw):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(requests, "request", raising)
    assert fetch_crossref_prefix("10.1234", user_agent="ua") is None


# ── build_user_agent ────────────────────────────────────────────────


def test_build_user_agent_includes_email():
    ua = build_user_agent("foo@bar.fr")
    assert "mailto:foo@bar.fr" in ua
    assert "BibliometrieUCA" in ua
