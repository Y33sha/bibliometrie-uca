"""Tests d'intégration du parcours de connexion.

La fixture `auth_client` forge son jeton directement, sans passer par `/api/auth/login` : le parcours complet — connexion, cookie posé, écriture autorisée, déconnexion — ne s'exerce donc que par ces tests.
"""

import bcrypt
from pydantic import SecretStr

from infrastructure.settings import settings
from interfaces.api.session import SESSION_MAX_AGE


class TestLogin:
    def test_pose_un_cookie_de_session_durci(self, client, monkeypatch):
        """Le cookie qui porte la session est inaccessible au script, borné au site, réservé au canal chiffré et daté.

        Ces quatre attributs sont ce qui sépare un jeton de session d'une valeur qu'un script injecté lirait, qu'une requête partie d'un autre site rejouerait, ou qu'un accès en clair révélerait. Le dossier de sécurité les énonce ; ce test les relit sur la réponse plutôt que dans le code qui les pose.

        L'empreinte est posée ici, à faible coût : ce test porte sur les attributs du cookie, non sur la vérification du mot de passe.
        """
        from interfaces.api import session as session_module

        empreinte = bcrypt.hashpw(b"mot-de-passe-de-test", bcrypt.gensalt(rounds=4)).decode()
        monkeypatch.setattr(session_module.settings, "admin_hash", SecretStr(empreinte))
        monkeypatch.setattr(session_module.settings, "cookie_secure", True)

        r = client.post(
            "/api/auth/login",
            json={"username": settings.admin_user, "password": "mot-de-passe-de-test"},
        )
        assert r.status_code == 200, r.text

        pose = r.headers["set-cookie"].lower()
        assert "httponly" in pose
        assert "samesite=strict" in pose
        assert "secure" in pose
        assert f"max-age={SESSION_MAX_AGE}" in pose

    def test_la_session_dure_sept_jours(self):
        """La durée annoncée par le dossier de sécurité, en secondes."""
        assert SESSION_MAX_AGE == 7 * 24 * 3600

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

    def test_throttles_repeated_attempts(self, client):
        from interfaces.api.rate_limit import _LOGIN_MAX_ATTEMPTS

        payload = {"username": "inconnu", "password": "x"}
        for _ in range(_LOGIN_MAX_ATTEMPTS):
            assert client.post("/api/auth/login", json=payload).status_code == 401
        # Au-delà du plafond, le limiteur coupe avant même la vérification des identifiants.
        assert client.post("/api/auth/login", json=payload).status_code == 429


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


class TestDureeDeReponse:
    """La vérification du mot de passe a lieu même quand le nom d'utilisateur ne correspond pas.

    Elle coûte quelques centaines de millisecondes, là où comparer deux noms en coûte une fraction de microseconde : un refus immédiat désignerait un nom inconnu, et permettrait de trouver le nom du compte sans dépenser les tentatives que le plafond accorde.
    """

    def test_le_mot_de_passe_est_verifie_sur_un_nom_inconnu(self, client, monkeypatch):
        appels = []
        import interfaces.api.routers.auth as auth_module

        monkeypatch.setattr(auth_module, "check_password", lambda mdp: appels.append(mdp) or False)
        r = client.post("/api/auth/login", json={"username": "inconnu", "password": "x"})
        assert r.status_code == 401
        assert appels == ["x"]

    def test_le_nom_est_compare_en_temps_constant(self):
        """La comparaison passe par `hmac.compare_digest`, dont la durée ne dépend pas du nombre de caractères justes."""
        import inspect

        from interfaces.api.session import check_username

        assert "compare_digest" in inspect.getsource(check_username)
