"""Tests du helper HTTP `http_retry`, versions synchrone et asynchrone.

Vérifie la politique de retry commune aux deux variantes : 429 et 5xx retentés jusqu'à `max_retries`, autres 4xx (404…) en échec immédiat sans retry, corps vide et erreurs réseau retentés.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest
import requests
import respx

from infrastructure.sources import http_retry
from infrastructure.sources.http_retry import http_request_with_retry_async

# ── variante synchrone (requests) ────────────────────────────────


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


# ── variante asynchrone (httpx) ──────────────────────────────────


class TestAsync:
    @pytest.mark.asyncio
    @respx.mock
    async def test_success_returns_json(self):
        route = respx.get("https://api.example/foo").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with httpx.AsyncClient() as client:
            data = await http_request_with_retry_async(
                client, "GET", "https://api.example/foo", label="test"
            )
        assert data == {"ok": True}
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_429_then_succeeds(self):
        route = respx.get("https://api.example/foo").mock(
            side_effect=[
                httpx.Response(429),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        async with httpx.AsyncClient() as client:
            data = await http_request_with_retry_async(
                client,
                "GET",
                "https://api.example/foo",
                initial_backoff=0.01,  # rapide pour les tests
                label="test",
            )
        assert data == {"ok": True}
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_5xx_is_retried(self):
        route = respx.get("https://api.example/foo").mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await http_request_with_retry_async(
                    client,
                    "GET",
                    "https://api.example/foo",
                    max_retries=3,
                    initial_backoff=0.01,
                    label="test",
                )
        assert route.call_count == 3  # 5xx retenté jusqu'au dernier essai

    @pytest.mark.asyncio
    @respx.mock
    async def test_4xx_fails_fast_without_retry(self):
        route = respx.get("https://api.example/foo").mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await http_request_with_retry_async(
                    client,
                    "GET",
                    "https://api.example/foo",
                    max_retries=3,
                    initial_backoff=0.01,
                    label="test",
                )
        assert route.call_count == 1  # aucun retry sur 4xx

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_on_persistent_network_error(self):
        respx.get("https://api.example/foo").mock(side_effect=httpx.ConnectError("refused"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.ConnectError):
                await http_request_with_retry_async(
                    client,
                    "GET",
                    "https://api.example/foo",
                    max_retries=2,
                    initial_backoff=0.01,
                    label="test",
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_empty_body_when_enabled(self):
        route = respx.get("https://api.example/foo").mock(
            side_effect=[
                httpx.Response(200, text=""),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        async with httpx.AsyncClient() as client:
            data = await http_request_with_retry_async(
                client,
                "GET",
                "https://api.example/foo",
                retry_on_empty_body=True,
                initial_backoff=0.01,
                label="test",
            )
        assert data == {"ok": True}
        assert route.call_count == 2
