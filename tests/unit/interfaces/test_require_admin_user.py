"""Les deux lectures de la session côté API : celle qui adapte, et celle qui refuse.

`current_admin_user` rend l'utilisateur ou `None`, laissant l'appelant décider quoi servir. `require_admin_user` ferme la porte. La seconde manquait : une lecture qu'on voulait réserver n'avait aucun moyen de l'être.
"""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from interfaces.api import deps


def _request(cookie: str | None = None) -> Request:
    headers = [(b"cookie", f"session={cookie}".encode())] if cookie is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.fixture
def session_reader(monkeypatch):
    """Remplace la lecture du jeton : seul `jeton-valide` porte un utilisateur."""
    monkeypatch.setattr(
        deps, "read_session", lambda token: "admin" if token == "jeton-valide" else None
    )


class TestCurrentAdminUser:
    def test_rend_l_utilisateur_de_la_session(self, session_reader):
        assert deps.current_admin_user(_request("jeton-valide")) == "admin"

    def test_rend_none_sans_cookie(self, session_reader):
        assert deps.current_admin_user(_request()) is None

    def test_rend_none_sur_un_jeton_invalide(self, session_reader):
        assert deps.current_admin_user(_request("jeton-forge")) is None


class TestRequireAdminUser:
    def test_rend_l_utilisateur_de_la_session(self, session_reader):
        assert deps.require_admin_user(_request("jeton-valide")) == "admin"

    def test_refuse_sans_cookie(self, session_reader):
        with pytest.raises(HTTPException) as excinfo:
            deps.require_admin_user(_request())
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail == "Non authentifié"

    def test_refuse_un_jeton_invalide(self, session_reader):
        """Un cookie présent mais dont la signature ne tient pas ne vaut pas mieux qu'aucun cookie."""
        with pytest.raises(HTTPException) as excinfo:
            deps.require_admin_user(_request("jeton-forge"))
        assert excinfo.value.status_code == 401
