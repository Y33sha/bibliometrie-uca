"""Tests du client `api.crossref.org/prefixes` (`parse_member_id`, `fetch_crossref_prefix`).

Mockent `httpx2.request` (utilisé par `http_request_with_retry`) pour ne pas dépendre du réseau.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx2

from infrastructure.sources.crossref.prefixes import fetch_crossref_prefix, parse_member_id


def _mock_response(status_code: int = 200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "x"
    resp.json.return_value = json_data
    return resp


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


# ── fetch_crossref_prefix ───────────────────────────────────────────


def test_fetch_crossref_prefix_ok(monkeypatch):
    monkeypatch.setattr(
        httpx2,
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
        httpx2,
        "request",
        lambda *a, **kw: _mock_response(200, {"message": {"name": "Foo"}}),
    )
    assert fetch_crossref_prefix("10.1234", user_agent="ua") == ("Foo", None)


def _router(monkeypatch, routes: dict[str, object]):
    """Répond selon le chemin appelé ; une URL absente de `routes` lève."""

    def request(method, url, **kw):
        for fragment, payload in routes.items():
            if fragment in url:
                return _mock_response(200, {"message": payload})
        raise AssertionError(f"appel inattendu : {url}")

    monkeypatch.setattr(httpx2, "request", request)


def test_fetch_crossref_prefix_takes_depositing_member_when_registered_one_is_idle(monkeypatch):
    """Le préfixe reste enregistré au nom d'un compte sans dépôt : la notice donne le compte vivant."""
    _router(
        monkeypatch,
        {
            "/prefixes/": {
                "name": "Saint Joseph University of Beirut (independent)",
                "member": "https://id.crossref.org/member/50585",
            },
            "/members/50585": {"counts": {"total-dois": 0}},
            "/works/": {
                "publisher": "Saint Joseph University of Beirut",
                "member": 54812,
            },
        },
    )
    assert fetch_crossref_prefix("10.70898", "10.70898/regards.v0i24.486", user_agent="ua") == (
        "Saint Joseph University of Beirut",
        54812,
    )


def test_fetch_crossref_prefix_keeps_registered_member_when_it_deposits(monkeypatch):
    _router(
        monkeypatch,
        {
            "/prefixes/": {"name": "Springer", "member": 297},
            "/members/297": {"counts": {"total-dois": 18946725}},
        },
    )
    assert fetch_crossref_prefix("10.1007", "10.1007/abc", user_agent="ua") == ("Springer", 297)


def test_fetch_crossref_prefix_without_sample_doi_asks_nothing_more(monkeypatch):
    _router(monkeypatch, {"/prefixes/": {"name": "Springer", "member": 297}})
    assert fetch_crossref_prefix("10.1007", user_agent="ua") == ("Springer", 297)


def test_fetch_crossref_prefix_missing_name_returns_none(monkeypatch):
    monkeypatch.setattr(
        httpx2,
        "request",
        lambda *a, **kw: _mock_response(200, {"message": {}}),
    )
    assert fetch_crossref_prefix("10.1234", user_agent="ua") is None


def test_fetch_crossref_prefix_http_error_returns_none(monkeypatch):
    def raising(*a, **kw):
        raise httpx2.ConnectError("boom")

    monkeypatch.setattr(httpx2, "request", raising)
    assert fetch_crossref_prefix("10.1234", user_agent="ua") is None
