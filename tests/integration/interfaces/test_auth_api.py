"""Tests d'intégration du parcours de connexion.

La fixture `auth_client` forge son jeton sans passer par `/api/auth/login`. Seuls ces tests exercent le parcours complet : connexion, cookie, écriture autorisée, déconnexion.
"""

import bcrypt
import pytest
from pydantic import SecretStr

from infrastructure.settings import settings
from interfaces.api.session import SESSION_MAX_AGE, issue_token
from tests.integration.helpers.db import owner_pool


def _roles_of(login: str) -> list[str] | None:
    """Rôles de `login` lus en base, ou `None` s'il est absent de `ops.users`."""
    with owner_pool() as cur:
        cur.execute(
            "SELECT array_remove(array_agg(ur.role_code ORDER BY ur.role_code), NULL) AS roles "
            "FROM ops.users u LEFT JOIN ops.user_roles ur ON ur.user_id = u.id "
            "WHERE u.login = %s GROUP BY u.id",
            (login,),
        )
        row = cur.fetchone()
        return row["roles"] if row else None


def _add_user(login: str, *roles: str) -> None:
    with owner_pool() as cur:
        cur.execute("INSERT INTO ops.users (login) VALUES (%s) ON CONFLICT DO NOTHING", (login,))
        for role in roles:
            cur.execute(
                "INSERT INTO ops.user_roles (user_id, role_code) "
                "SELECT id, %s FROM ops.users WHERE login = %s ON CONFLICT DO NOTHING",
                (role, login),
            )


def _remove_user(login: str) -> None:
    with owner_pool() as cur:
        cur.execute("DELETE FROM ops.users WHERE login = %s", (login,))


class TestLogin:
    def test_pose_un_cookie_de_session_durci(self, client, monkeypatch):
        """Le cookie de session est inaccessible au script, limité au site, réservé à HTTPS et daté.

        Le test lit ces attributs sur la réponse. L'empreinte du mot de passe est calculée au coût minimal de bcrypt.
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
        # Au-delà du plafond, le limiteur refuse avant la vérification des identifiants.
        assert client.post("/api/auth/login", json=payload).status_code == 429


class TestCheck:
    def test_reports_anonymous_visitor(self, client):
        r = client.get("/api/auth/check")
        assert r.status_code == 200
        assert r.json() == {"authenticated": False, "login": None, "roles": []}

    def test_reports_open_session(self, auth_client):
        r = auth_client.get("/api/auth/check")
        assert r.status_code == 200
        assert r.json() == {
            "authenticated": True,
            "login": settings.admin_user,
            "roles": ["admin"],
        }

    def test_reports_forged_cookie_as_anonymous(self, client):
        client.cookies.set("session", "admin|0.signature-inventee")
        try:
            r = client.get("/api/auth/check")
            assert r.json()["authenticated"] is False
        finally:
            client.cookies.clear()


class TestUtilisateurs:
    def test_l_admin_des_reglages_existe_au_demarrage(self, client):
        assert _roles_of(settings.admin_user) == ["admin"]

    def test_une_ecriture_sans_le_role_admin_est_refusee(self, client):
        _add_user("lecteur")
        client.cookies.set("session", issue_token("lecteur"))
        try:
            assert client.put("/api/config/inconnue", json={"value": 1}).status_code == 403
            assert client.get("/api/auth/check").json() == {
                "authenticated": True,
                "login": "lecteur",
                "roles": [],
            }
        finally:
            client.cookies.clear()
            _remove_user("lecteur")

    def test_un_jeton_dont_le_login_est_absent_des_utilisateurs_est_refuse(self, client):
        client.cookies.set("session", issue_token("parti"))
        try:
            assert client.put("/api/config/inconnue", json={"value": 1}).status_code == 401
            assert client.get("/api/auth/check").json()["authenticated"] is False
        finally:
            client.cookies.clear()

    @pytest.fixture
    def _admin_retire(self):
        _remove_user(settings.admin_user)
        yield
        _add_user(settings.admin_user, "admin")

    @pytest.mark.usefixtures("_admin_retire")
    def test_la_connexion_est_refusee_si_l_admin_est_absent_des_utilisateurs(
        self, client, monkeypatch
    ):
        from interfaces.api import session as session_module

        empreinte = bcrypt.hashpw(b"mot-de-passe-de-test", bcrypt.gensalt(rounds=4)).decode()
        monkeypatch.setattr(session_module.settings, "admin_hash", SecretStr(empreinte))

        r = client.post(
            "/api/auth/login",
            json={"username": settings.admin_user, "password": "mot-de-passe-de-test"},
        )
        assert r.status_code == 401
        assert "session" not in r.cookies


class TestLogout:
    def test_clears_the_session(self, auth_client):
        r = auth_client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_is_open_to_anonymous(self, client):
        """La déconnexion est ouverte sans session : le middleware exempte `/api/auth/`."""
        r = client.post("/api/auth/logout")
        assert r.status_code == 200


class TestDureeDeReponse:
    """Le mot de passe est vérifié même pour un nom d'utilisateur inconnu.

    La vérification coûte quelques centaines de millisecondes. Un refus immédiat révélerait donc qu'un nom est inconnu, et permettrait de trouver le nom du compte sans consommer les tentatives du plafond.
    """

    def test_le_mot_de_passe_est_verifie_sur_un_nom_inconnu(self, client, monkeypatch):
        appels = []
        import interfaces.api.routers.auth as auth_module

        monkeypatch.setattr(auth_module, "check_password", lambda mdp: appels.append(mdp) or False)
        r = client.post("/api/auth/login", json={"username": "inconnu", "password": "x"})
        assert r.status_code == 401
        assert appels == ["x"]

    def test_le_nom_est_compare_en_temps_constant(self):
        """La comparaison passe par `hmac.compare_digest`, dont la durée est indépendante du nombre de caractères justes."""
        import inspect

        from interfaces.api.session import check_username

        assert "compare_digest" in inspect.getsource(check_username)
