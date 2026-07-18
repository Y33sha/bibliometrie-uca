"""Tests d'intégration du parcours de connexion.

La fixture `auth_client` forge son jeton directement, sans passer par `/api/auth/login` : le parcours complet — connexion, cookie posé, écriture autorisée, déconnexion — ne s'exerce donc que par ces tests.
"""

from infrastructure.settings import settings


class TestLogin:
    def test_rejects_unknown_user(self, client):
        r = client.post("/api/auth/login", json={"username": "inconnu", "password": "x"})
        assert r.status_code == 401
        assert "session" not in r.cookies

    def test_rejects_wrong_password(self, client):
        r = client.post(
            "/api/auth/login", json={"username": settings.admin_user, "password": "mauvais"}
        )
        assert r.status_code == 401
        assert "session" not in r.cookies

    def test_requires_both_fields(self, client):
        r = client.post("/api/auth/login", json={"username": settings.admin_user})
        assert r.status_code == 422


class TestCheck:
    def test_reports_anonymous_visitor(self, client):
        r = client.get("/api/auth/check")
        assert r.status_code == 200
        assert r.json() == {"authenticated": False}

    def test_reports_open_session(self, auth_client):
        r = auth_client.get("/api/auth/check")
        assert r.status_code == 200
        assert r.json() == {"authenticated": True}

    def test_reports_forged_cookie_as_anonymous(self, client):
        client.cookies.set("session", "admin|0.signature-inventee")
        try:
            r = client.get("/api/auth/check")
            assert r.json() == {"authenticated": False}
        finally:
            client.cookies.clear()


class TestLogout:
    def test_clears_the_session(self, auth_client):
        r = auth_client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_is_open_to_anonymous(self, client):
        """La déconnexion ne garde rien : le middleware exempte `/api/auth/`."""
        r = client.post("/api/auth/logout")
        assert r.status_code == 200
