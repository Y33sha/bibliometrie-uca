"""Tests du client `doi.org/ra` (`fetch_registration_agencies`).

Mockent `httpx2.request` (utilisé par `http_request_with_retry`) pour ne pas dépendre du réseau.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx2

from infrastructure.sources.doi_org import registration_agency
from infrastructure.sources.doi_org.registration_agency import fetch_registration_agencies


def _mock_response(status_code: int = 200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.is_redirect = False
    resp.text = "x"
    resp.json.return_value = json_data
    return resp


def test_one_request_per_batch_of_prefixes(monkeypatch):
    urls: list[str] = []

    def request(method, url, **kw):
        urls.append(url)
        prefixes = url.rsplit("/", 1)[1].split(",")
        return _mock_response(200, [{"DOI": p, "RA": "Crossref"} for p in prefixes])

    monkeypatch.setattr(httpx2, "request", request)
    monkeypatch.setattr(registration_agency, "DOI_ORG_RA_BATCH", 2)

    result = list(fetch_registration_agencies(["10.1", "10.2", "10.3"], user_agent="ua"))

    assert urls == ["https://doi.org/ra/10.1,10.2", "https://doi.org/ra/10.3"]
    assert result == [("10.1", "Crossref"), ("10.2", "Crossref"), ("10.3", "Crossref")]


def test_unknown_prefix_has_no_agency(monkeypatch):
    payload = [
        {"DOI": "10.5281", "RA": "DataCite"},
        {"DOI": "10.99999", "status": "DOI does not exist"},
    ]
    monkeypatch.setattr(httpx2, "request", lambda *a, **kw: _mock_response(200, payload))

    result = list(fetch_registration_agencies(["10.5281", "10.99999"], user_agent="ua"))

    assert result == [("10.5281", "DataCite"), ("10.99999", None)]


def test_failed_batch_yields_nothing(monkeypatch):
    """Un 4xx écarte le lot : ses préfixes restent à résoudre."""
    monkeypatch.setattr(httpx2, "request", lambda *a, **kw: _mock_response(400))

    assert list(fetch_registration_agencies(["10.1038"], user_agent="ua")) == []


def test_answer_for_an_unasked_prefix_is_ignored(monkeypatch):
    monkeypatch.setattr(
        httpx2,
        "request",
        lambda *a, **kw: _mock_response(200, [{"DOI": "10.9999", "RA": "Crossref"}]),
    )

    assert list(fetch_registration_agencies(["10.1038"], user_agent="ua")) == []
