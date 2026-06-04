"""Tests du client API ROR (`infrastructure.sources.ror`).

Mockent `requests.get` pour ne pas dépendre du réseau.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import requests

from infrastructure.sources import ror

LOGGER = logging.getLogger("test")
BASE_URL = "https://api.ror.org/v2/organizations"


def _mock_response(status_code: int = 200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def test_fetch_ror_record_success(monkeypatch):
    record = {"id": "https://ror.org/01abc23", "names": [{"value": "UCA"}]}
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _mock_response(200, record))

    out = ror.fetch_ror_record("01abc23", base_url=BASE_URL, user_agent="ua", logger=LOGGER)

    assert out == record


def test_fetch_ror_record_404_returns_none(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _mock_response(404))

    out = ror.fetch_ror_record("unknown", base_url=BASE_URL, user_agent="ua", logger=LOGGER)

    assert out is None


def test_fetch_ror_record_network_error_returns_none(monkeypatch):
    def _boom(*a, **kw):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(requests, "get", _boom)

    out = ror.fetch_ror_record("01abc23", base_url=BASE_URL, user_agent="ua", logger=LOGGER)

    assert out is None


def test_build_ror_user_agent():
    assert ror.build_ror_user_agent("contact@uca.fr") == (
        "bibliometrie-uca/1.0 (mailto:contact@uca.fr)"
    )
