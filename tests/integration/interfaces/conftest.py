"""Fixtures partagées pour les tests d'intégration API.

Fournit :
- `client` : TestClient FastAPI pointant sur bibliometrie_test (module-scoped).
- `auth_client` : TestClient avec cookie session admin valide.

Le sync Engine SQLAlchemy du lifespan FastAPI est redirigé vers
bibliometrie_test par monkey-patch de `build_sync_engine` avant l'import
de l'app.
"""

import os

import pytest
from sqlalchemy import URL, Engine, create_engine

DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))


def _build_test_sync_engine() -> Engine:
    """Engine SA sync sur bibliometrie_test, garde-fou DML installé comme le vrai."""
    from infrastructure.db.dml_guard import install_dml_guard

    url = URL.create(
        drivername="postgresql+psycopg",
        username=DB_USER,
        password=DB_PASSWORD or None,
        host=DB_HOST,
        port=DB_PORT,
        database="bibliometrie_test",
    )
    engine = create_engine(url, pool_size=1, max_overflow=2, pool_pre_ping=True)
    install_dml_guard(engine)
    return engine


# Patcher AVANT import de l'app
import infrastructure.db.engine as _engine_module  # noqa: E402

_engine_module.build_sync_engine = _build_test_sync_engine

from fastapi.testclient import TestClient  # noqa: E402

import interfaces.api.app as _app_module  # noqa: E402
from interfaces.api.app import app  # noqa: E402

# Patcher la copie locale dans app.py (import-time capture du nom)
_app_module.build_sync_engine = _build_test_sync_engine

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
