"""Régression : `http_request_with_retry` (sync) échoue immédiatement sur un 4xx
déterministe (≠ 429) au lieu de le retenter 3× — un 404/400 ne se résout pas en
retentant. Les 5xx et les erreurs réseau restent retentés."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from infrastructure.sources import http_retry


def _resp(status: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(response=r)
    else:
        r.raise_for_status.return_value = None
        r.text = "{}"
        r.json.return_value = {}
    return r


def test_4xx_fails_fast_without_retry():
    resp = _resp(404)
    with (
        patch.object(http_retry.requests, "request", return_value=resp) as req,
        patch.object(http_retry.time, "sleep"),
    ):
        with pytest.raises(requests.HTTPError):
            http_retry.http_request_with_retry("GET", "http://x", label="t", max_retries=3)
    assert req.call_count == 1  # aucun retry sur 4xx


def test_5xx_is_retried():
    resp = _resp(503)
    with (
        patch.object(http_retry.requests, "request", return_value=resp) as req,
        patch.object(http_retry.time, "sleep"),
    ):
        with pytest.raises(requests.HTTPError):
            http_retry.http_request_with_retry("GET", "http://x", label="t", max_retries=3)
    assert req.call_count == 3  # 5xx retenté jusqu'au dernier essai


def test_success_returns_json():
    with (
        patch.object(http_retry.requests, "request", return_value=_resp(200)),
        patch.object(http_retry.time, "sleep"),
    ):
        assert http_retry.http_request_with_retry("GET", "http://x", label="t") == {}
