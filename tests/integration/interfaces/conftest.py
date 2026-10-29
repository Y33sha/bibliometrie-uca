"""Fixtures partagées des tests d'intégration de l'API.

L'application se connecte à bibliometrie_test : son constructeur d'engine est substitué avant son import.
"""

import os

import pytest
from sqlalchemy import URL, Engine, create_engine

DB_OWNER_USER = os.environ["DB_OWNER_USER"]
DB_OWNER_PASSWORD = os.environ.get("DB_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))


def _build_test_sync_engine(identity: str = "pipeline") -> Engine:
    """Engine SQLAlchemy synchrone sur bibliometrie_test, avec les garde-fous de l'engine de production.

    `identity` choisit le rôle de connexion : celui de l'API pour l'application, celui du pipeline ou du propriétaire du schéma pour les jeux de données. Les tests exercent donc les droits de production.
    """
    from infrastructure.db.engine import install_engine_guards
    from infrastructure.settings import settings as _s

    if identity == "owner":
        username, password = DB_OWNER_USER, DB_OWNER_PASSWORD
    else:
        username = getattr(_s, f"db_{identity}_user")
        password = getattr(_s, f"db_{identity}_password").get_secret_value()
    url = URL.create(
        drivername="postgresql+psycopg",
        username=username,
        password=password or None,
        host=DB_HOST,
        port=DB_PORT,
        database="bibliometrie_test",
    )
    engine = create_engine(url, pool_size=1, max_overflow=2, pool_pre_ping=True)
    install_engine_guards(engine)
    return engine


# Le constructeur est substitué avant l'import de l'application.
import infrastructure.db.engine as _engine_module  # noqa: E402

_engine_module.build_sync_engine = _build_test_sync_engine

from fastapi.testclient import TestClient  # noqa: E402

import interfaces.api.app as _app_module  # noqa: E402
from interfaces.api.app import app  # noqa: E402

# app.py importe le nom du constructeur : sa copie locale est substituée aussi.
_app_module.build_sync_engine = _build_test_sync_engine

from collections.abc import Iterator

from infrastructure.settings import settings as _settings  # noqa: E402
from tests.integration.helpers.db import ConfigRow, config_rows, reset_database  # noqa: E402

# Les tests s'exécutent sur http://testserver, et le client renvoie un cookie marqué Secure seulement en HTTPS.
_settings.cookie_secure = False


@pytest.fixture(scope="session")
def _config_defaults() -> list[ConfigRow]:
    """Réglages de `ops.config` posés par les migrations, lus avant le premier module de tests d'API."""
    return config_rows()


@pytest.fixture(scope="module", autouse=True)
def _reset_database_after_module(_config_defaults: list[ConfigRow]) -> Iterator[None]:
    """Remet la base dans son état d'après les migrations à la fin de chaque module.

    Les tests d'API valident leurs écritures dans la base : sans remise à zéro, elles pèseraient sur les modules suivants.
    """
    yield
    reset_database(_config_defaults)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Isole chaque test des compteurs globaux des limiteurs de débit."""
    from interfaces.api.rate_limit import reset_export_slots, reset_rate_limiters

    reset_rate_limiters()
    reset_export_slots()
    yield


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """Client de l'application, sans session."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth_client() -> Iterator[TestClient]:
    """Client de l'application, avec un cookie de session valide."""
    from interfaces.api.session import issue_token

    with TestClient(app, raise_server_exceptions=False) as c:
        c.cookies.set("session", issue_token(_settings.admin_user))
        yield c
