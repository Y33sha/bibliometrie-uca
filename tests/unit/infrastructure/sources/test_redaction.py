"""Tests de l'assainissement des URL sortantes écrites dans les journaux.

Non-régression : la clé d'API OpenAlex voyage en paramètre de requête, et le message d'erreur composé par httpx sur un statut d'échec porte l'URL entière. Un 401 ou un 403 — le cas d'une clé invalide ou révoquée — écrivait donc la clé en clair dès qu'un appelant journalisait l'exception.
"""

import httpx
import pytest

from infrastructure.sources.redaction import REDACTED, raise_for_status, redact_url

_API_KEY = "cle-secrete-de-test"


class TestRedactUrl:
    def test_remplace_les_valeurs_en_gardant_les_noms(self):
        redacted = redact_url("https://api.openalex.org/works?api_key=abc123&per_page=200")
        assert redacted == (
            f"https://api.openalex.org/works?api_key={REDACTED}&per_page={REDACTED}"
        )

    def test_url_sans_parametre_inchangee(self):
        url = "https://doi.org/ra/10.1000%2Fxyz"
        assert redact_url(url) == url

    def test_accepte_une_url_httpx(self):
        assert _API_KEY not in redact_url(httpx.URL(f"https://api.example/x?api_key={_API_KEY}"))

    def test_valeur_vide_traitee_comme_les_autres(self):
        assert (
            redact_url("https://api.example/x?mailto=")
            == f"https://api.example/x?mailto={REDACTED}"
        )

    def test_identifiants_dans_l_hote_retires(self):
        redacted = redact_url("https://user:motdepasse@api.example:8443/x")
        assert "motdepasse" not in redacted
        assert redacted == f"https://{REDACTED}@api.example:8443/x"

    def test_un_parametre_inconnu_est_couvert(self):
        """Les valeurs sont retirées toutes ensemble : un paramètre porteur d'un identifiant ajouté plus tard ne passe pas au travers faute de figurer dans une liste."""
        assert "secret" not in redact_url("https://api.example/x?jeton_maison=secret")


class TestRaiseForStatus:
    def _response(self, status: int) -> httpx.Response:
        request = httpx.Request("GET", f"https://api.openalex.org/works?api_key={_API_KEY}")
        return httpx.Response(status, request=request)

    def test_succes_ne_leve_rien(self):
        assert raise_for_status(self._response(200)) is None

    @pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
    def test_le_message_ne_porte_pas_la_cle(self, status: int):
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            raise_for_status(self._response(status))
        assert _API_KEY not in str(excinfo.value)
        assert _API_KEY not in repr(excinfo.value)

    def test_le_message_reste_diagnostique(self):
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            raise_for_status(self._response(403))
        message = str(excinfo.value)
        assert "403" in message
        assert "api.openalex.org/works" in message
        assert "api_key" in message  # le nom du paramètre, jamais sa valeur

    def test_aucune_exception_chainee_ne_reintroduit_l_url(self):
        """L'erreur naît hors d'un bloc `except` : rien à quoi la chaîner, donc aucun message d'origine à réafficher dans une trace."""
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            raise_for_status(self._response(403))
        assert excinfo.value.__cause__ is None
        assert excinfo.value.__context__ is None

    def test_le_type_attendu_par_les_adapters_est_conserve(self):
        """Les adapters de sources attrapent `httpx.HTTPStatusError` nommément et lisent le statut sur la réponse."""
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            raise_for_status(self._response(429))
        assert excinfo.value.response.status_code == 429
