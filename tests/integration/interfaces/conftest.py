"""Fixtures partagées pour les tests d'intégration API.

Fournit :
- `client` : TestClient FastAPI pointant sur bibliometrie_test (module-scoped).
- `auth_client` : TestClient avec cookie session admin valide.
- `pool_cursor` : helper pour insérer des données via le même pool que
  celui utilisé par l'API (visible depuis les endpoints testés).
- `seed_publications` : fixture data-seeding pour les tests de
  caractérisation de `/api/publications`, `/api/persons`, etc.

Le pool est créé sur bibliometrie_test et remplace get_cursor dans les
modules routers via monkey-patching. La base est recréée à chaque
session par le conftest racine intégration (schema.sql frais).
"""

import os
from contextlib import contextmanager

import pytest
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

DB_USER = os.environ.get("DB_USER", "lalecoz")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))

_test_db_args = {"dbname": "bibliometrie_test", "user": DB_USER, "host": DB_HOST, "port": DB_PORT}
if DB_PASSWORD:
    _test_db_args["password"] = DB_PASSWORD

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
import interfaces.api.deps  # noqa: E402

interfaces.api.deps.get_cursor = _test_get_cursor

from fastapi.testclient import TestClient  # noqa: E402

import interfaces.api.app as _app_module  # noqa: E402
from interfaces.api.app import app  # noqa: E402

# Patcher les copies locales de get_cursor dans les routers
_app_module.get_cursor = _test_get_cursor
for router_module in [
    getattr(__import__(f"interfaces.api.routers.{name}", fromlist=[name]), name, None)
    for name in [
        "publications",
        "persons",
        "laboratories",
        "structures",
        "addresses",
        "authorships",
        "admin_duplicates",
        "admin_person_duplicates",
        "pub_stats",
        "feedback",
        "config",
        "publishers",
        "journals",
        "docs",
        "auth",
        "hal_problems",
    ]
]:
    if router_module and hasattr(router_module, "get_cursor"):
        router_module.get_cursor = _test_get_cursor

from infrastructure.settings import settings as _settings  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient FastAPI pointant vers bibliometrie_test."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth_client() -> TestClient:
    """Client authentifié (cookie session valide)."""
    import time

    from interfaces.api.deps import _sign_token

    with TestClient(app, raise_server_exceptions=False) as c:
        token = _sign_token(f"{_settings.admin_user}|{int(time.time())}")
        c.cookies.set("session", token)
        yield c


@contextmanager
def pool_cursor():
    """Curseur sur le pool de test, avec commit au sortir (visible depuis l'API)."""
    conn = _test_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _test_pool.putconn(conn)


def truncate_all() -> None:
    """Vide toutes les tables applicatives (préserve les référentiels seed)."""
    with pool_cursor() as cur:
        cur.execute("""
            TRUNCATE TABLE authorships, source_authorships, source_publications,
                publications, persons, persons_rh, person_identifiers,
                person_name_forms, journals, publishers, addresses,
                address_structures, staging, audit_log
            RESTART IDENTITY CASCADE
        """)
