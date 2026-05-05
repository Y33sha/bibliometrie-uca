"""Fixtures partagées pour les tests d'intégration API.

Fournit :
- `client` : TestClient FastAPI pointant sur bibliometrie_test (module-scoped).
- `auth_client` : TestClient avec cookie session admin valide.

Le pool async FastAPI est redirigé vers bibliometrie_test par monkey-patch
de `build_async_pool` avant l'import de l'app.
"""

import os

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))

_test_db_args = {"dbname": "bibliometrie_test", "user": DB_USER, "host": DB_HOST, "port": DB_PORT}
if DB_PASSWORD:
    _test_db_args["password"] = DB_PASSWORD


# ── Pool async pour le lifespan FastAPI ─────────────────────────
#
# Monkey-patch de build_async_pool : le lifespan l'appelle pour créer
# son pool, on lui fournit un pool pointant sur bibliometrie_test. Le
# lifespan se charge ensuite d'ouvrir/fermer ce pool normalement.


def _build_test_async_pool() -> AsyncConnectionPool:
    """Pool async non ouvert, sur bibliometrie_test. Ouvert par le lifespan.

    Même config que le pool prod (cf. `build_async_pool`) — notamment
    `prepare_threshold=1` pour coller au comportement réel.
    """
    return AsyncConnectionPool(
        conninfo="",
        min_size=1,
        max_size=3,
        kwargs={**_test_db_args, "row_factory": dict_row, "prepare_threshold": 1},
        open=False,
    )


# Patcher AVANT import de l'app
import infrastructure.db.async_connection as _async_conn  # noqa: E402

_async_conn.build_async_pool = _build_test_async_pool

from fastapi.testclient import TestClient  # noqa: E402

import interfaces.api.app as _app_module  # noqa: E402
from interfaces.api.app import app  # noqa: E402

# Patcher la copie locale dans app.py (import-time capture du nom)
_app_module.build_async_pool = _build_test_async_pool

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
