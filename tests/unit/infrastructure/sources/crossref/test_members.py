"""Tests du client Crossref Members (`infrastructure.sources.crossref.members`).

Mockent `requests.get` pour ne pas dépendre du réseau.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import requests

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
