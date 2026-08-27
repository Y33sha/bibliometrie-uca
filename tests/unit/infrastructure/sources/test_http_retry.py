"""Tests du helper HTTP `http_retry`, versions synchrone et asynchrone.

Vérifie la politique de retry commune aux deux variantes : 429 et 5xx retentés jusqu'à `max_retries`, autres 4xx (404…) en échec immédiat sans retry, corps vide et erreurs réseau retentés.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from infrastructure.sources import http_retry
from infrastructure.sources.http_retry import http_request_with_retry_async

_API_KEY = "cle-secrete-de-test"

# ── variante synchrone (httpx) ────────────────────────────────


def _resp(status: int) -> MagicMock:
    """Réponse simulée. `is_success` et `reason_phrase` sont ce que lit `raise_for_status`, qui compose lui-même le message d'erreur."""
    r = MagicMock()
    r.status_code = status
    r.is_success = 200 <= status < 300
    r.reason_phrase = "Error" if status >= 400 else "OK"
    if not r.is_success:
        r.text = ""
    else:
        r.text = "{}"
        r.json.return_value = {}
    return r


def test_4xx_fails_fast_without_retry():
    resp = _resp(404)
    with (
        patch.object(http_retry.httpx, "request", return_value=resp) as req,
        patch.object(http_retry.time, "sleep"),
    ):
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            http_retry.http_request_with_retry("GET", "http://x", label="t", max_retries=3)
    assert req.call_count == 1  # aucun retry sur 4xx
    # Non-régression : l'erreur que les appelants journalisent ne porte pas la requête,
    # dont les paramètres transportent la clé d'API.
    assert _API_KEY not in str(excinfo.value)


def test_5xx_is_retried():
    resp = _resp(503)
    with (
        patch.object(http_retry.httpx, "request", return_value=resp) as req,
        patch.object(http_retry.time, "sleep"),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            http_retry.http_request_with_retry("GET", "http://x", label="t", max_retries=3)
    assert req.call_count == 3  # 5xx retenté jusqu'au dernier essai


def test_5xx_with_breaker_raises_source_unavailable():
    """Sous circuit-breaker, un 5xx qui épuise ses retries lève `SourceUnavailableError` et compte un échec au breaker."""
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        SourceUnavailableError,
        reset_current_breaker,
        set_current_breaker,
    )

    breaker = SourceCircuitBreaker("hal", threshold=1)
    token = set_current_breaker(breaker)
    try:
        resp = _resp(503)
        with (
            patch.object(http_retry.httpx, "request", return_value=resp) as req,
            patch.object(http_retry.time, "sleep"),
        ):
            with pytest.raises(SourceUnavailableError):
                http_retry.http_request_with_retry("GET", "http://x", label="t", max_retries=3)
        assert req.call_count == 3  # 3 tentatives, puis coupure
        assert breaker.tripped  # l'échec est compté au breaker
    finally:
        reset_current_breaker(token)


def test_success_returns_json():
    with (
        patch.object(http_retry.httpx, "request", return_value=_resp(200)),
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

    @pytest.mark.asyncio
    @respx.mock
    async def test_le_parametre_secret_ne_sort_pas_dans_l_erreur(self):
        """Non-régression : une clé d'API passée en paramètre de requête n'apparaît pas dans l'erreur levée, que les appelants journalisent."""
        respx.get("https://api.example/foo").mock(return_value=httpx.Response(403))
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError) as excinfo:
                await http_request_with_retry_async(
                    client,
                    "GET",
                    "https://api.example/foo",
                    params={"api_key": _API_KEY},
                    initial_backoff=0.01,
                    label="test",
                )
        assert _API_KEY not in str(excinfo.value)
        assert _API_KEY not in repr(excinfo.value)


class TestRedirections:
    """Le helper ne suit pas les redirections : l'hôte joint est celui que la requête désigne.

    Les points d'entrée des sources répondent directement. Un statut 3xx signale donc une réponse inattendue, non une étape à franchir — et les en-têtes d'authentification propres à un fournisseur, que le client HTTP ne retire pas comme il retire `Authorization`, ne quittent pas leur destinataire.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_une_redirection_est_une_erreur(self):
        respx.get("https://api.example/foo").mock(
            return_value=httpx.Response(302, headers={"location": "https://ailleurs.example/foo"})
        )
        ailleurs = respx.get("https://ailleurs.example/foo").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await http_request_with_retry_async(
                    client, "GET", "https://api.example/foo", initial_backoff=0.01, label="test"
                )
        assert ailleurs.call_count == 0  # la destination n'est pas jointe
