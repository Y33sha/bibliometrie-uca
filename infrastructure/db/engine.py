"""Engine SQLAlchemy synchrone (driver psycopg3), unique pour l'API, le pipeline et les scripts en ligne de commande."""

import os
from typing import Literal

import psycopg  # noqa: F401 — driver chargé par SA via la URL postgresql+psycopg://
from pydantic import SecretStr
from sqlalchemy import URL, Engine, create_engine

from infrastructure.db.query_cancellation import install_query_cancellation
from infrastructure.db.read_only_guard import install_read_only_guard
from infrastructure.settings import settings

_sync_engine: Engine | None = None


DbIdentity = Literal["owner", "app", "pipeline"]


def db_url(identity: DbIdentity = "pipeline") -> URL:
    """URL de connexion PostgreSQL, construite depuis les réglages (réutilisée par Alembic).

    `identity` désigne le rôle PostgreSQL du processus (cf. `infrastructure/db/roles.sql`) : celui du pipeline par défaut. Un rôle non configuré fait échouer la construction.
    """
    username: str = getattr(settings, f"db_{identity}_user")
    secret: SecretStr = getattr(settings, f"db_{identity}_password")
    if not username:
        variable = f"DB_{identity.upper()}_USER"
        raise RuntimeError(
            f"{variable} et {variable.replace('_USER', '_PASSWORD')} sont requis dans "
            "l'environnement (rôles créés par `infrastructure/db/roles.sql`)."
        )
    password = secret.get_secret_value()
    query = {"sslmode": settings.db_sslmode} if settings.db_sslmode else {}
    return URL.create(
        drivername="postgresql+psycopg",
        username=username,
        password=password,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        query=query,
    )


def build_sync_engine(identity: DbIdentity = "pipeline") -> Engine:
    """Construit l'engine synchrone pour le rôle `identity` (cf. `db_url`).

    Pool : `db_pool_min` connexions persistantes, jusqu'à `db_pool_max` sous charge ; `pool_pre_ping` écarte les connexions perdues.

    Sous pytest, refuse toute base sans suffixe `_test` : le conftest redirige l'engine vers la base de test, et ce contrôle protège la base de production si la redirection échoue.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not settings.db_name.endswith("_test"):
        raise RuntimeError(
            f"build_sync_engine refusé sous pytest sur DB '{settings.db_name}' "
            f"(suffixe '_test' requis). Vérifier le monkey-patch dans le conftest."
        )
    engine = create_engine(
        db_url(identity),
        pool_size=settings.db_pool_min,
        max_overflow=settings.db_pool_max - settings.db_pool_min,
        pool_pre_ping=True,
    )
    install_engine_guards(engine)
    return engine


def install_engine_guards(engine: Engine) -> None:
    """Attache les garde-fous de toute connexion du projet : refus d'écrire pendant une requête de lecture, sortie du recensement des annulations au retour dans le pool.

    Un engine monté hors de `build_sync_engine`, comme celui des tests, les reçoit en un appel.
    """
    install_read_only_guard(engine)
    install_query_cancellation(engine)


def set_sync_engine(engine: Engine | None) -> None:
    """Enregistre (ou désenregistre) l'engine sync global."""
    global _sync_engine
    _sync_engine = engine


def get_sync_engine() -> Engine:
    """Engine global, construit au premier appel pour le pipeline et les scripts ; l'API le construit au démarrage."""
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = build_sync_engine()
    return _sync_engine
