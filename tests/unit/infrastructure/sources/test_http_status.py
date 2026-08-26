"""Tests de la levée d'erreur de statut sur les requêtes vers les sources.

Non-régression : la clé d'API OpenAlex voyage en paramètre de requête, et le message que compose `httpx.Response.raise_for_status` porte l'URL entière. Un 401 ou un 403 — le cas d'une clé invalide ou révoquée — écrivait donc la clé en clair dès qu'un appelant journalisait l'exception.
"""

import httpx
import pytest

from infrastructure.sources.http_status import raise_for_status

_API_KEY = "cle-secrete-de-test"


def _response(status: int) -> httpx.Response:
    request = httpx.Request("GET", f"https://api.openalex.org/works?api_key={_API_KEY}")
    return httpx.Response(status, request=request)


def test_succes_ne_leve_rien():
    assert raise_for_status(_response(200)) is None


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_le_message_ne_porte_ni_la_cle_ni_l_url(status: int):
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        raise_for_status(_response(status))
    for rendu in (str(excinfo.value), repr(excinfo.value)):
        assert _API_KEY not in rendu
        assert "api.openalex.org" not in rendu


def test_le_message_porte_le_statut():
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        raise_for_status(_response(403))
    assert str(excinfo.value) == "HTTP 403 Forbidden"


def test_aucune_exception_chainee_ne_reintroduit_l_url():
    """L'erreur naît hors d'un bloc `except` : rien à quoi la chaîner, donc aucun message d'origine à réafficher dans une trace."""
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        raise_for_status(_response(403))
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_le_statut_reste_lisible_sur_la_reponse():
    """Les adapters de sources attrapent `httpx.HTTPStatusError` nommément et décident sur `response.status_code` — jamais sur le message."""
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        raise_for_status(_response(429))
    assert excinfo.value.response.status_code == 429
