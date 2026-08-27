"""Lecture de la session d'administration côté API.

`admin_user_or_none` rend l'utilisateur porté par le cookie de session, ou `None`, sans jamais refuser l'appel : l'appelant décide de ce qu'il sert selon la réponse.
"""

from starlette.requests import Request

from interfaces.api import deps


def _request(cookie: str | None = None) -> Request:
    headers = [(b"cookie", f"session={cookie}".encode())] if cookie is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


class TestAdminUserOrNone:
    def _lecture_simulee(self, monkeypatch):
        """Lecture de jeton simulée : seul `jeton-valide` porte un utilisateur."""
        monkeypatch.setattr(
            deps, "read_session", lambda token: "admin" if token == "jeton-valide" else None
        )

    def test_rend_l_utilisateur_de_la_session(self, monkeypatch):
        self._lecture_simulee(monkeypatch)
        assert deps.admin_user_or_none(_request("jeton-valide")) == "admin"

    def test_rend_none_sans_cookie(self, monkeypatch):
        self._lecture_simulee(monkeypatch)
        assert deps.admin_user_or_none(_request()) is None

    def test_rend_none_sur_un_jeton_invalide(self, monkeypatch):
        """Un cookie présent dont la signature ne tient pas vaut un cookie absent."""
        self._lecture_simulee(monkeypatch)
        assert deps.admin_user_or_none(_request("jeton-forge")) is None
