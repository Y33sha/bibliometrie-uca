"""Lecture de la session côté API.

`session_user` renvoie l'utilisateur désigné par le cookie de session, avec ses rôles, ou `None`, sans jamais refuser l'appel : l'appelant décide de ce qu'il sert selon la réponse.
"""

from starlette.requests import Request

from domain.users import Role, SessionUser
from interfaces.api import deps


def _request(cookie: str | None = None) -> Request:
    headers = [(b"cookie", f"session={cookie}".encode())] if cookie is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


class _Users:
    """Utilisateurs simulés : `admin` a le rôle admin, `lecteur` aucun rôle."""

    def __init__(self, conn: object) -> None:
        pass

    def roles_of(self, login: str) -> frozenset[str] | None:
        return {"admin": frozenset({Role.ADMIN}), "lecteur": frozenset()}.get(login)


class TestSessionUser:
    def _simuler(self, monkeypatch):
        """Seul un jeton de la forme `jeton-<login>` désigne un utilisateur."""
        monkeypatch.setattr(
            deps,
            "read_session",
            lambda token: token.removeprefix("jeton-") if token.startswith("jeton-") else None,
        )
        monkeypatch.setattr(deps, "user_repository", _Users)

    def test_rend_l_utilisateur_et_ses_roles(self, monkeypatch):
        self._simuler(monkeypatch)
        user = deps.session_user(_request("jeton-admin"), conn=None)
        assert user == SessionUser("admin", frozenset({Role.ADMIN}))
        assert user.is_admin

    def test_rend_un_utilisateur_sans_role(self, monkeypatch):
        self._simuler(monkeypatch)
        user = deps.session_user(_request("jeton-lecteur"), conn=None)
        assert user == SessionUser("lecteur", frozenset())
        assert not user.is_admin

    def test_rend_none_sans_cookie(self, monkeypatch):
        self._simuler(monkeypatch)
        assert deps.session_user(_request(), conn=None) is None

    def test_rend_none_sur_un_jeton_invalide(self, monkeypatch):
        """Un cookie dont la signature est invalide équivaut à un cookie absent."""
        self._simuler(monkeypatch)
        assert deps.session_user(_request("forge"), conn=None) is None

    def test_rend_none_pour_un_login_absent_des_utilisateurs(self, monkeypatch):
        """Un jeton valide dont le login est absent de `ops.users` équivaut à un cookie absent."""
        self._simuler(monkeypatch)
        assert deps.session_user(_request("jeton-parti"), conn=None) is None
