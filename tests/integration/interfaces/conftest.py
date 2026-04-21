"""Fixtures partagées pour les tests d'intégration API.

Fournit :
- `client` : TestClient FastAPI pointant sur bibliometrie_test (module-scoped).
- `auth_client` : TestClient avec cookie session admin valide.
- `pool_cursor` : helper sync pour seeder via le même pool que l'API.
- `async_pool_cursor` : helper async pour tester directement des queries
  async (hors TestClient). Le pool sync existant reste utilisable pour
  les seeds de tests API (le lifespan FastAPI + TestClient gèrent leur
  propre pool async via le monkey-patch de build_async_pool).

Le pool sync remplace get_cursor dans les modules routers via
monkey-patching. Le pool async remplace build_async_pool via
monkey-patching, ce qui redirige le lifespan FastAPI vers
bibliometrie_test.
"""

import os
from contextlib import asynccontextmanager, contextmanager

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

DB_USER = os.environ.get("DB_USER", "lalecoz")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))

_test_db_args = {"dbname": "bibliometrie_test", "user": DB_USER, "host": DB_HOST, "port": DB_PORT}
if DB_PASSWORD:
    _test_db_args["password"] = DB_PASSWORD

_test_pool = ConnectionPool(
    conninfo="",
    min_size=1,
    max_size=3,
    kwargs={**_test_db_args, "row_factory": dict_row},
    open=True,
)


# ── Pool async pour le lifespan FastAPI (§2.12) ────────────────
#
# Monkey-patch de build_async_pool : le lifespan l'appelle pour créer
# son pool, on lui fournit un pool pointant sur bibliometrie_test. Le
# lifespan se charge ensuite d'ouvrir/fermer ce pool normalement.


def _build_test_async_pool() -> AsyncConnectionPool:
    """Pool async non ouvert, sur bibliometrie_test. Ouvert par le lifespan."""
    return AsyncConnectionPool(
        conninfo="",
        min_size=1,
        max_size=3,
        kwargs={**_test_db_args, "row_factory": dict_row},
        open=False,
    )


# Patcher AVANT import de l'app
import infrastructure.db.async_connection as _async_conn  # noqa: E402

_async_conn.build_async_pool = _build_test_async_pool


@contextmanager
def _test_get_cursor():
    conn = _test_pool.getconn()
    # Ping : si la connexion pool est stale (timeout server pendant la phase
    # de collecte pytest), la jeter et en demander une neuve.
    try:
        with conn.cursor() as _ping:
            _ping.execute("SELECT 1")
    except psycopg.Error:
        # psycopg_pool n'a pas de flag close=True ; on ferme la connexion
        # nous-mêmes, la pool la discardera au putconn suivant.
        conn.close()
        _test_pool.putconn(conn)
        conn = _test_pool.getconn()
    try:
        with conn.cursor() as cur:
            yield cur, conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except psycopg.InterfaceError:
            pass  # connexion déjà fermée côté serveur, rien à rollback
        raise
    finally:
        _test_pool.putconn(conn)


# Patcher get_cursor AVANT l'import de l'app
import interfaces.api.deps  # noqa: E402

interfaces.api.deps.get_cursor = _test_get_cursor

from fastapi.testclient import TestClient  # noqa: E402

import interfaces.api.app as _app_module  # noqa: E402
from interfaces.api.app import app  # noqa: E402

# Patcher aussi build_async_pool dans app.py (import-time capture du nom)
_app_module.build_async_pool = _build_test_async_pool

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
        "admin_feedback",
        "admin_pipeline",
        "stats",
        "config",
        "publishers",
        "journals",
        "docs",
        "auth",
        "hal_problems",
        "perimeters",
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
    """Curseur sync sur le pool de test, commit au sortir (visible depuis l'API)."""
    conn = _test_pool.getconn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _test_pool.putconn(conn)


@asynccontextmanager
async def async_pool_cursor():
    """Curseur async sur une connexion dédiée à bibliometrie_test.

    Pour les tests qui appellent directement les fonctions async de
    `infrastructure/db/queries/` hors du TestClient. Connexion fraîche
    à chaque appel (pas de pool partagé) pour éviter les conflits de
    loop entre pytest-asyncio (loop par test) et le lifespan TestClient.
    """
    conn = await psycopg.AsyncConnection.connect(**_test_db_args, row_factory=dict_row)
    try:
        async with conn.cursor() as cur:
            yield cur
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        await conn.close()


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
