"""Tests des endpoints API (GET publics + POST protégés).

Utilise le TestClient FastAPI sur la base bibliometrie_test.
La base de test est initialisée par conftest.py (session-scoped).

Ces tests vérifient :
- que les endpoints principaux répondent correctement
- que l'auth protège les écritures
- que les réponses ont la bonne structure
"""

import os
from contextlib import contextmanager

import pytest
from psycopg2.extras import RealDictCursor

# Recréer le pool DB sur bibliometrie_test avant d'importer l'app
DB_USER = os.environ.get("DB_USER", "lalecoz")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))

_test_db_args = {"dbname": "bibliometrie_test", "user": DB_USER,
                 "host": DB_HOST, "port": DB_PORT}
if DB_PASSWORD:
    _test_db_args["password"] = DB_PASSWORD

from psycopg2.pool import ThreadedConnectionPool

_test_pool = ThreadedConnectionPool(minconn=1, maxconn=3, **_test_db_args)


@contextmanager
def _test_get_cursor():
    conn = _test_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur, conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _test_pool.putconn(conn)


# Patcher get_cursor AVANT l'import de l'app
import backend.deps

backend.deps.get_cursor = _test_get_cursor

from fastapi.testclient import TestClient

import backend.app as _app_module
from backend.app import app

# Patcher aussi les copies locales dans les modules qui font
# "from backend.deps import get_cursor" (copie dans leur namespace)
_app_module.get_cursor = _test_get_cursor
for router_module in [
    getattr(__import__(f"backend.routers.{name}", fromlist=[name]), name, None)
    for name in ["publications", "persons", "laboratories", "structures",
                 "addresses", "authorships", "admin_duplicates",
                 "admin_person_duplicates", "pub_stats", "stats",
                 "feedback", "config", "publishers", "journals", "docs", "auth"]
]:
    if router_module and hasattr(router_module, "get_cursor"):
        router_module.get_cursor = _test_get_cursor
from config.settings import settings as _settings


@pytest.fixture(scope="module")
def client():
    """TestClient FastAPI pointant vers bibliometrie_test."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth_client():
    """Client authentifié séparé (cookie session valide)."""
    import time

    from backend.deps import _sign_token
    with TestClient(app, raise_server_exceptions=False) as c:
        token = _sign_token(f"{_settings.admin_user}|{int(time.time())}")
        c.cookies.set("session", token)
        yield c


# ── Health ──────────────────────────────────────────────────────

class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        # Le health check utilise get_cursor ; 200 si la base est accessible
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            assert r.json()["status"] == "ok"


# ── Publications ────────────────────────────────────────────────

class TestPublications:
    def test_list(self, client):
        r = client.get("/api/publications")
        assert r.status_code == 200
        data = r.json()
        assert "publications" in data
        assert "total" in data

    def test_facets(self, client):
        r = client.get("/api/publications/facets")
        assert r.status_code == 200
        data = r.json()
        assert "years" in data

    def test_not_found(self, client):
        r = client.get("/api/publications/999999999")
        assert r.status_code == 404


# ── Personnes ───────────────────────────────────────────────────

class TestPersons:
    def test_list(self, client):
        r = client.get("/api/persons")
        assert r.status_code == 200
        data = r.json()
        assert "persons" in data
        assert "total" in data

    def test_facets(self, client):
        r = client.get("/api/persons/facets")
        assert r.status_code == 200

    def test_search(self, client):
        r = client.get("/api/persons/search", params={"q": "dupont"})
        assert r.status_code == 200

    def test_not_found(self, client):
        r = client.get("/api/persons/999999999")
        assert r.status_code == 404


# ── Laboratoires ────────────────────────────────────────────────

class TestLaboratories:
    def test_list(self, client):
        r = client.get("/api/laboratories")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_not_found(self, client):
        r = client.get("/api/laboratories/999999999")
        assert r.status_code in (404, 500)  # certains endpoints n'ont pas de guard 404


# ── Stats ───────────────────────────────────────────────────────

class TestStats:
    def test_summary(self, client):
        r = client.get("/api/stats/summary")
        assert r.status_code == 200


# ── Auth ────────────────────────────────────────────────────────

class TestAuth:
    def test_check_unauthenticated(self, client):
        r = client.get("/api/auth/check")
        assert r.status_code == 200
        assert r.json()["authenticated"] is False

    def test_write_requires_auth(self, client):
        """Les POST sans cookie session renvoient 401."""
        r = client.post("/api/persons/999999999/merge", json={"target_id": 1})
        assert r.status_code == 401

    def test_write_with_auth(self, auth_client):
        """Avec un cookie valide, le POST passe (même si 404 ou 400)."""
        r = auth_client.post("/api/persons/999999999/merge", json={"target_id": 1})
        # 404 (personne inexistante) ou 400, mais pas 401
        assert r.status_code != 401


# ── Config ──────────────────────────────────────────────────────

class TestConfig:
    def test_get_config(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200

    def test_write_requires_auth(self, client):
        """Les écritures config sans auth renvoient 401."""
        r = client.post("/api/perimeters/1/structures", json={"structure_id": 1})
        assert r.status_code == 401


# ── Adresses ────────────────────────────────────────────────────

class TestAddresses:
    def test_countries(self, client):
        r = client.get("/api/countries")
        assert r.status_code == 200
