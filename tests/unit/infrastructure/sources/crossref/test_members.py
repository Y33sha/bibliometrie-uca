"""Tests du client Crossref Members (`infrastructure.sources.crossref.members`).

Mockent `requests.get` pour ne pas dépendre du réseau.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import requests

from infrastructure.sources.circuit_breaker import SourceCircuitBreaker
from infrastructure.sources.crossref import members

LOGGER = logging.getLogger("test")


def _mock_response(status_code: int = 200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def test_fetch_crossref_member_success(monkeypatch):
    msg = {"id": 297, "primary-name": "Springer", "location": "Berlin, Germany"}
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _mock_response(200, {"message": msg}))

    out = members.fetch_crossref_member(297, user_agent="ua", logger=LOGGER)

    assert out == msg


def test_fetch_crossref_member_404_returns_none(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _mock_response(404))

    out = members.fetch_crossref_member(999999, user_agent="ua", logger=LOGGER)

    assert out is None


def test_fetch_crossref_member_no_message_returns_none(monkeypatch):
    # Corps 200 sans bloc `message` exploitable -> None.
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _mock_response(200, {"status": "ok"}))

    out = members.fetch_crossref_member(297, user_agent="ua", logger=LOGGER)

    assert out is None


def test_fetch_crossref_member_network_error_returns_none(monkeypatch):
    def _boom(*a, **kw):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(requests, "get", _boom)

    out = members.fetch_crossref_member(297, user_agent="ua", logger=LOGGER)

    assert out is None


# ── Coupe-circuit (budget Crossref) ──────────────────────────────


def test_429_records_failure_and_returns_none(monkeypatch):
    """Régression : un 429 compte un échec sur le breaker (au lieu d'être avalé)."""
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _mock_response(429))
    breaker = SourceCircuitBreaker("crossref", threshold=1)

    out = members.fetch_crossref_member(297, user_agent="ua", logger=LOGGER, breaker=breaker)

    assert out is None
    assert breaker.tripped  # threshold=1 → tripé dès le premier 429


def test_tripped_breaker_skips_api(monkeypatch):
    """Breaker tripé → on ne tape plus l'API (les fetches restants sont sautés sans coût)."""
    calls = {"n": 0}

    def _get(*a, **kw):
        calls["n"] += 1
        return _mock_response(200, {"message": {"id": 1}})

    monkeypatch.setattr(requests, "get", _get)
    breaker = SourceCircuitBreaker("crossref", threshold=1)
    breaker.record_failure()  # tripe

    out = members.fetch_crossref_member(297, user_agent="ua", logger=LOGGER, breaker=breaker)

    assert out is None
    assert calls["n"] == 0  # aucun appel réseau


def test_success_resets_consecutive_failures(monkeypatch):
    """Un fetch réussi remet le compteur d'échecs à zéro (429 transitoires non fatals)."""
    msg = {"id": 297}
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _mock_response(200, {"message": msg}))
    breaker = SourceCircuitBreaker("crossref", threshold=3)
    breaker.record_failure()
    breaker.record_failure()  # 2 échecs consécutifs

    out = members.fetch_crossref_member(297, user_agent="ua", logger=LOGGER, breaker=breaker)

    assert out == msg
    breaker.record_failure()  # après reset : 1 seul échec
    assert not breaker.tripped
