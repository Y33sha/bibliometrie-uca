"""Fixtures partagées pour les tests d'intégration API.

Fournit :
- `client` : TestClient FastAPI pointant sur bibliometrie_test (module-scoped).
- `auth_client` : TestClient avec cookie session admin valide.

Le sync Engine SQLAlchemy du lifespan FastAPI est redirigé vers
bibliometrie_test par monkey-patch de `build_sync_engine` avant l'import
de l'app.
"""

import logging
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


@pytest.fixture(autouse=True)
def _fail_on_escaped_dml():
    """Échoue si une écriture API échappe à un command handler.

    `db_conn` émet un warning quand son commit de fin rattrape du DML non
    committé (écriture qui ne passe pas par un command handler committant). On le
    transforme en échec de test pour verrouiller l'invariant « toute écriture API
    commit avant la réponse », y compris pour les futurs endpoints — c'est ce qui
    rend sûre la lecture seule de `db_conn` (commit de fin retiré).
    """
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            message = record.getMessage()
            if "command handler" in message:
                captured.append(message)

    handler = _Capture()
    deps_logger = logging.getLogger("interfaces.api.deps")
    # `setup_logger` (dictConfig) désactive les loggers existants ; on le réactive
    # le temps du test, sinon `logger.warning` du garde-fou est un no-op et un
    # éventuel DML échappé passerait inaperçu.
    was_disabled = deps_logger.disabled
    deps_logger.disabled = False
    deps_logger.addHandler(handler)
    try:
        yield
    finally:
        deps_logger.removeHandler(handler)
        deps_logger.disabled = was_disabled
    assert not captured, "Écriture(s) hors command handler détectée(s) : " + " | ".join(captured)


@pytest.fixture(scope="module")
def client() -> TestClient:
    """TestClient FastAPI pointant vers bibliometrie_test."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth_client() -> TestClient:
    """Client authentifié (cookie session valide)."""
    from interfaces.api.session import issue_token

    with TestClient(app, raise_server_exceptions=False) as c:
        c.cookies.set("session", issue_token(_settings.admin_user))
        yield c
