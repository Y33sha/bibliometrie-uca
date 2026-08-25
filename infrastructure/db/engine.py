"""Engine SQLAlchemy synchrone basé sur le driver psycopg3.

Un seul Engine sync utilisé par toute l'application :
- L'API FastAPI consomme cet engine via `db_conn` (les routes `def` tournent dans le threadpool Starlette).
- Le pipeline et les scripts CLI ouvrent leurs propres connexions via `engine.begin()` / `engine.connect()`.

Le driver `postgresql+psycopg` permet d'accéder aux features psycopg3 (server-side cursors, COPY) via `Connection.connection.driver_connection` si besoin.
"""

import os

import psycopg  # noqa: F401 — driver chargé par SA via la URL postgresql+psycopg://
from sqlalchemy import URL, Engine, create_engine

from infrastructure.db.dml_guard import install_dml_guard
from infrastructure.settings import settings

_sync_engine: Engine | None = None


def db_url(*, application: bool = False) -> URL:
    """URL de connexion Postgres construite depuis les settings (réutilisée par Alembic).

    `application` demande l'identité restreinte de l'API (`db_app_user`), un rôle limité à la lecture et à l'écriture des données. Sans elle configurée, ou pour tout autre appelant — migrations, pipeline, scripts de maintenance —, la connexion se fait avec l'identité principale, propriétaire du schéma : eux seuls modifient sa structure, rafraîchissent les vues matérialisées et vident des tables.

    `db_sslmode`, s'il est défini, est passé en paramètre de connexion `sslmode`.
    """
    if application and settings.db_app_user:
        username, password = settings.db_app_user, settings.db_app_password
    else:
        username, password = settings.db_user, settings.db_password
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


def build_sync_engine(*, application: bool = False) -> Engine:
    """Construit l'Engine SQLAlchemy synchrone (driver psycopg3).

    Utilisé par toute la surface (API, pipeline, CLI). `application` demande l'identité restreinte de l'API (cf. `db_url`). Paramètres pool :
    - `pool_size = db_pool_min` : connexions persistantes
    - `max_overflow = db_pool_max - db_pool_min` : connexions supplémentaires sous charge, fermées au retour
    - `pool_pre_ping = True` : détecte les connexions perdues (timeout réseau, reset SGBD) avant de les remettre en service

    Garde-fou : sous pytest, refuse toute base dont le nom n'a pas le suffixe `_test`. Les tests redirigent l'engine vers la base de test par monkey-patch (conftest) ; ce backstop empêche qu'un test écrive dans la base de production si ce monkey-patch venait à être contourné.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not settings.db_name.endswith("_test"):
        raise RuntimeError(
            f"build_sync_engine refusé sous pytest sur DB '{settings.db_name}' "
            f"(suffixe '_test' requis). Vérifier le monkey-patch dans le conftest."
        )
    engine = create_engine(
        db_url(application=application),
        pool_size=settings.db_pool_min,
        max_overflow=settings.db_pool_max - settings.db_pool_min,
        pool_pre_ping=True,
    )
    install_dml_guard(engine)
    return engine


def set_sync_engine(engine: Engine | None) -> None:
    """Enregistre (ou désenregistre) l'engine sync global."""
    global _sync_engine
    _sync_engine = engine


def get_sync_engine() -> Engine:
    """Retourne l'engine sync global, en le construisant à la demande.

    L'API initialise l'engine au démarrage via le lifespan, mais les scripts CLI et le pipeline n'ont pas de cycle de vie applicatif : ils déclenchent la construction lazy au premier appel.
    """
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = build_sync_engine()
    return _sync_engine
