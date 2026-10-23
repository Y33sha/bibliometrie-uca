"""Tests du helper HTTP `http_retry`, versions synchrone et asynchrone.

Vérifie la politique de retry commune aux deux variantes : 429, 5xx, erreurs réseau et corps vide retentés jusqu'à `max_retries`, puis `SourceUnavailableError` ; autres 4xx (404…) en échec immédiat sans retry. Les requêtes s'exécutent sous le circuit-breaker de la fixture `breaker`.
"""

import contextvars
from unittest.mock import MagicMock, patch

import httpx2
import pytest

from pipeline.http import http_retry
from pipeline.http.circuit_breaker import SourceUnavailableError, source_circuit_breaker
from pipeline.http.http_retry import (
    http_get_text_with_retry_async,
    http_request_with_retry_async,
    lookup_json_async,
)
from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE

_API_KEY = "cle-secrete-de-test"

pytestmark = pytest.mark.usefixtures("breaker")

# ── variante synchrone (httpx2) ────────────────────────────────


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
        patch.object(http_retry.httpx2, "request", return_value=resp) as req,
        patch.object(http_retry.time, "sleep"),
    ):
        with pytest.raises(httpx2.HTTPStatusError) as excinfo:
            http_retry.http_request_with_retry("GET", "http://x", label="t", max_retries=3)
    assert req.call_count == 1  # aucun retry sur 4xx
    # Non-régression : l'erreur que les appelants journalisent ne porte pas la requête,
    # dont les paramètres transportent la clé d'API.
    assert _API_KEY not in str(excinfo.value)


def test_une_erreur_reseau_sans_message_est_journalisee_par_son_type(caplog):
    """Un délai dépassé de httpx a un message vide : le journal donne au moins son type."""
    resp = _resp(200)
    with (
        patch.object(http_retry.httpx2, "request", side_effect=[httpx2.ReadTimeout(""), resp]),
        patch.object(http_retry.time, "sleep"),
        caplog.at_level("WARNING"),
    ):
        http_retry.http_request_with_retry("GET", "http://x", label="t", max_retries=3)
    assert "ReadTimeout" in caplog.text


def test_5xx_exhausted_raises_source_unavailable():
    """Un 5xx qui épuise ses retries lève `SourceUnavailableError` et compte un échec au breaker."""
    with source_circuit_breaker("hal", threshold=1) as breaker:
        resp = _resp(503)
        with (
            patch.object(http_retry.httpx2, "request", return_value=resp) as req,
            patch.object(http_retry.time, "sleep"),
        ):
            with pytest.raises(SourceUnavailableError):
                http_retry.http_request_with_retry("GET", "http://x", label="t", max_retries=3)
        assert req.call_count == 3  # 3 tentatives, puis coupure
        assert breaker.tripped  # l'échec est compté au breaker


def test_une_requete_hors_de_l_acces_a_une_source_est_refusee():
    """Hors de l'accès à une source, aucun breaker n'est posé : la requête n'est pas émise."""
    with patch.object(http_retry.httpx2, "request") as req, pytest.raises(RuntimeError):
        # Un contexte vide : la ContextVar y a sa valeur par défaut, sans breaker.
        contextvars.Context().run(http_retry.http_request_with_retry, "GET", "http://x")
    req.assert_not_called()


def test_success_returns_json():
    with (
        patch.object(http_retry.httpx2, "request", return_value=_resp(200)),
        patch.object(http_retry.time, "sleep"),
    ):
        assert http_retry.http_request_with_retry("GET", "http://x", label="t") == {}


# ── variante asynchrone (httpx2) ──────────────────────────────────


class TestAsyncText:
    @pytest.mark.asyncio
    async def test_returns_body_as_text(self, http_mock):
        http_mock.get("https://api.example/enregistrement source.xml").mock(
            return_value=httpx2.Response(200, text="<record/>")
        )
        async with httpx2.AsyncClient() as client:
            body = await http_get_text_with_retry_async(
                client, "https://api.example/enregistrement source.xml", label="test"
            )
        assert body == "<record/>"

    @pytest.mark.asyncio
    async def test_retries_empty_body(self, http_mock):
        route = http_mock.get("https://api.example/enregistrement source.xml").mock(
            side_effect=[httpx2.Response(200, text=""), httpx2.Response(200, text="<record/>")]
        )
        async with httpx2.AsyncClient() as client:
            body = await http_get_text_with_retry_async(
                client,
                "https://api.example/enregistrement source.xml",
                initial_backoff=0.01,
                label="test",
            )
        assert body == "<record/>"
        assert route.call_count == 2


class TestAsync:
    @pytest.mark.asyncio
    async def test_success_returns_json(self, http_mock):
        route = http_mock.get("https://api.example/foo").mock(
            return_value=httpx2.Response(200, json={"ok": True})
        )
        async with httpx2.AsyncClient() as client:
            data = await http_request_with_retry_async(
                client, "GET", "https://api.example/foo", label="test"
            )
        assert data == {"ok": True}
        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self, http_mock):
        route = http_mock.get("https://api.example/foo").mock(
            side_effect=[
                httpx2.Response(429),
                httpx2.Response(200, json={"ok": True}),
            ]
        )
        async with httpx2.AsyncClient() as client:
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
    async def test_5xx_is_retried(self, http_mock):
        route = http_mock.get("https://api.example/foo").mock(return_value=httpx2.Response(503))
        async with httpx2.AsyncClient() as client:
            with pytest.raises(SourceUnavailableError):
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
    async def test_4xx_fails_fast_without_retry(self, http_mock):
        route = http_mock.get("https://api.example/foo").mock(return_value=httpx2.Response(404))
        async with httpx2.AsyncClient() as client:
            with pytest.raises(httpx2.HTTPStatusError):
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
    async def test_persistent_network_error_raises_source_unavailable(self, http_mock):
        http_mock.get("https://api.example/foo").mock(side_effect=httpx2.ConnectError("refused"))
        async with httpx2.AsyncClient() as client:
            with pytest.raises(SourceUnavailableError):
                await http_request_with_retry_async(
                    client,
                    "GET",
                    "https://api.example/foo",
                    max_retries=2,
                    initial_backoff=0.01,
                    label="test",
                )

    @pytest.mark.asyncio
    async def test_retries_on_empty_body_when_enabled(self, http_mock):
        route = http_mock.get("https://api.example/foo").mock(
            side_effect=[
                httpx2.Response(200, text=""),
                httpx2.Response(200, json={"ok": True}),
            ]
        )
        async with httpx2.AsyncClient() as client:
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
    async def test_persistent_empty_body_raises_source_unavailable(self, http_mock):
        """Un corps vide qui épuise ses retries compte un échec au breaker, comme un 429 : WoS signale ainsi un dépassement de débit."""
        http_mock.get("https://api.example/foo").mock(return_value=httpx2.Response(200, text=""))
        async with httpx2.AsyncClient() as client:
            with (
                source_circuit_breaker("test", threshold=1) as breaker,
                pytest.raises(SourceUnavailableError),
            ):
                await http_request_with_retry_async(
                    client,
                    "GET",
                    "https://api.example/foo",
                    retry_on_empty_body=True,
                    max_retries=2,
                    initial_backoff=0.01,
                    label="test",
                )
        assert breaker.tripped

    @pytest.mark.asyncio
    async def test_le_parametre_secret_ne_sort_pas_dans_l_erreur(self, http_mock):
        """Non-régression : une clé d'API passée en paramètre de requête n'apparaît pas dans l'erreur levée, que les appelants journalisent."""
        http_mock.get("https://api.example/foo").mock(return_value=httpx2.Response(403))
        async with httpx2.AsyncClient() as client:
            with pytest.raises(httpx2.HTTPStatusError) as excinfo:
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
    """Le helper ne suit une redirection que vers le même hôte, pour une requête GET, et une seule fois : l'hôte joint reste celui que la requête désigne.

    Les en-têtes d'authentification propres à un fournisseur, que le client HTTP ne retire pas comme il retire `Authorization`, ne quittent donc pas leur destinataire.
    """

    @pytest.mark.asyncio
    async def test_une_redirection_vers_le_meme_hote_est_suivie(self, http_mock):
        http_mock.get("https://api.example/alias").mock(
            return_value=httpx2.Response(301, headers={"location": "/principal"})
        )
        principal = http_mock.get("https://api.example/principal").mock(
            return_value=httpx2.Response(200, json={"ok": True})
        )
        async with httpx2.AsyncClient() as client:
            data = await http_request_with_retry_async(
                client, "GET", "https://api.example/alias", initial_backoff=0.01, label="test"
            )
        assert data == {"ok": True}
        assert principal.call_count == 1

    @pytest.mark.asyncio
    async def test_un_second_saut_est_une_erreur(self, http_mock):
        http_mock.get("https://api.example/a").mock(
            return_value=httpx2.Response(301, headers={"location": "/b"})
        )
        http_mock.get("https://api.example/b").mock(
            return_value=httpx2.Response(301, headers={"location": "/c"})
        )
        fin = http_mock.get("https://api.example/c").mock(
            return_value=httpx2.Response(200, json={"ok": True})
        )
        async with httpx2.AsyncClient() as client:
            with pytest.raises(httpx2.HTTPStatusError):
                await http_request_with_retry_async(
                    client, "GET", "https://api.example/a", initial_backoff=0.01, label="test"
                )
        assert fin.call_count == 0

    @pytest.mark.asyncio
    async def test_une_requete_post_redirigee_est_une_erreur(self, http_mock):
        http_mock.post("https://api.example/search").mock(
            return_value=httpx2.Response(307, headers={"location": "/autre"})
        )
        autre = http_mock.post("https://api.example/autre").mock(
            return_value=httpx2.Response(200, json={"ok": True})
        )
        async with httpx2.AsyncClient() as client:
            with pytest.raises(httpx2.HTTPStatusError):
                await http_request_with_retry_async(
                    client, "POST", "https://api.example/search", initial_backoff=0.01, label="test"
                )
        assert autre.call_count == 0

    @pytest.mark.asyncio
    async def test_une_redirection_vers_un_autre_hote_est_une_erreur(self, http_mock):
        http_mock.get("https://api.example/foo").mock(
            return_value=httpx2.Response(302, headers={"location": "https://ailleurs.example/foo"})
        )
        ailleurs = http_mock.get("https://ailleurs.example/foo").mock(
            return_value=httpx2.Response(200, json={"ok": True})
        )
        async with httpx2.AsyncClient() as client:
            with pytest.raises(httpx2.HTTPStatusError):
                await http_request_with_retry_async(
                    client, "GET", "https://api.example/foo", initial_backoff=0.01, label="test"
                )
        assert ailleurs.call_count == 0  # la destination n'est pas jointe


class TestLookupJsonAsync:
    """Classement d'une requête d'élément : trouvé, absent (404), source indisponible."""

    @pytest.mark.asyncio
    async def test_found_returns_body(self, http_mock):
        http_mock.get("https://api.example/a").mock(
            return_value=httpx2.Response(200, json={"ok": True})
        )
        async with httpx2.AsyncClient() as client:
            outcome = await lookup_json_async(client, "GET", "https://api.example/a", label="t")
        assert outcome == {"ok": True}

    @pytest.mark.asyncio
    async def test_404_is_not_found(self, http_mock):
        http_mock.get("https://api.example/a").mock(return_value=httpx2.Response(404))
        async with httpx2.AsyncClient() as client:
            outcome = await lookup_json_async(client, "GET", "https://api.example/a", label="t")
        assert outcome is NOT_FOUND

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [403, 503])
    async def test_other_http_error_is_unavailable(self, http_mock, status):
        http_mock.get("https://api.example/a").mock(return_value=httpx2.Response(status))
        async with httpx2.AsyncClient() as client:
            outcome = await lookup_json_async(
                client, "GET", "https://api.example/a", initial_backoff=0.01, label="t"
            )
        assert outcome is UNAVAILABLE

    @pytest.mark.asyncio
    async def test_search_endpoint_404_is_unavailable(self, http_mock):
        """Sur un endpoint de recherche, un 404 désigne l'endpoint : l'absence de l'élément n'est pas établie."""
        http_mock.get("https://api.example/search").mock(return_value=httpx2.Response(404))
        async with httpx2.AsyncClient() as client:
            outcome = await lookup_json_async(
                client,
                "GET",
                "https://api.example/search",
                not_found_statuses=frozenset(),
                label="t",
            )
        assert outcome is UNAVAILABLE

    @pytest.mark.asyncio
    async def test_source_specific_not_found_status(self, http_mock):
        http_mock.get("https://api.example/a").mock(return_value=httpx2.Response(400))
        async with httpx2.AsyncClient() as client:
            outcome = await lookup_json_async(
                client,
                "GET",
                "https://api.example/a",
                not_found_statuses=frozenset({400}),
                label="t",
            )
        assert outcome is NOT_FOUND

    @pytest.mark.asyncio
    async def test_network_error_is_unavailable(self, http_mock):
        http_mock.get("https://api.example/a").mock(side_effect=httpx2.ConnectError("refused"))
        async with httpx2.AsyncClient() as client:
            outcome = await lookup_json_async(
                client, "GET", "https://api.example/a", initial_backoff=0.01, label="t"
            )
        assert outcome is UNAVAILABLE

    @pytest.mark.asyncio
    async def test_invalid_json_is_unavailable(self, http_mock):
        http_mock.get("https://api.example/a").mock(
            return_value=httpx2.Response(200, text="pas du JSON")
        )
        async with httpx2.AsyncClient() as client:
            outcome = await lookup_json_async(
                client, "GET", "https://api.example/a", initial_backoff=0.01, label="t"
            )
        assert outcome is UNAVAILABLE

    @pytest.mark.asyncio
    async def test_tripped_breaker_is_unavailable_without_request(self, http_mock):
        from pipeline.http.circuit_breaker import source_circuit_breaker

        route = http_mock.get("https://api.example/a").mock(return_value=httpx2.Response(200))
        with source_circuit_breaker("test", threshold=1) as breaker:
            breaker.record_failure()
            async with httpx2.AsyncClient() as client:
                outcome = await lookup_json_async(client, "GET", "https://api.example/a", label="t")
        assert outcome is UNAVAILABLE
        assert route.call_count == 0
