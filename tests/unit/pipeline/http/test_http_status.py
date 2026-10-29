"""Tests de la levée d'erreur de statut sur les requêtes vers les sources.

Non-régression : la clé d'API OpenAlex est un paramètre de requête, et le message que compose `httpx2.Response.raise_for_status` contient l'URL entière. Un 401 ou un 403 (clé invalide ou révoquée) écrirait la clé en clair dans le journal de l'appelant.
"""

import httpx2
import pytest

from pipeline.http.http_status import raise_for_status

_API_KEY = "cle-secrete-de-test"


def _response(status: int) -> httpx2.Response:
    request = httpx2.Request("GET", f"https://api.openalex.org/works?api_key={_API_KEY}")
    return httpx2.Response(status, request=request)


def test_succes_ne_leve_rien():
    assert raise_for_status(_response(200)) is None


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_le_message_ne_porte_ni_la_cle_ni_l_url(status: int):
    with pytest.raises(httpx2.HTTPStatusError) as excinfo:
        raise_for_status(_response(status))
    for rendu in (str(excinfo.value), repr(excinfo.value)):
        assert _API_KEY not in rendu
        assert "api.openalex.org" not in rendu


def test_le_message_porte_le_statut():
    with pytest.raises(httpx2.HTTPStatusError) as excinfo:
        raise_for_status(_response(403))
    assert str(excinfo.value) == "HTTP 403 Forbidden"


def test_aucune_exception_chainee_ne_reintroduit_l_url():
    """L'erreur est levée hors d'un bloc `except` : elle n'a aucune exception chaînée dont la trace afficherait le message."""
    with pytest.raises(httpx2.HTTPStatusError) as excinfo:
        raise_for_status(_response(403))
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_le_statut_reste_lisible_sur_la_reponse():
    """L'erreur donne accès au statut de la réponse, sur lequel décident les adaptateurs des sources."""
    with pytest.raises(httpx2.HTTPStatusError) as excinfo:
        raise_for_status(_response(429))
    assert excinfo.value.response.status_code == 429
