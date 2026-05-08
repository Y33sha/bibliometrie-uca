"""Engines SQLAlchemy basés sur le driver psycopg3.

Deux engines coexistent : `AsyncEngine` pour FastAPI (côté API),
`Engine` sync pour le pipeline et les scripts CLI. Les deux utilisent
le driver psycopg3 sous le capot (URL `postgresql+psycopg://...`),
donc aucun changement côté DB et les features psycopg (server-side
cursors, COPY, etc.) restent accessibles via
`Connection.connection.driver_connection` si besoin.

Cohabite avec le pool psycopg `infrastructure/db/async_connection.py`
et les `psycopg.connect()` directs du pipeline pendant la phase de
migration (chantier docs/chantiers/sqlalchemy-core-adoption.md).
À terme (Phase 4), seuls les engines SQLAlchemy subsistent.
"""

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from infrastructure.settings import settings

_async_engine: AsyncEngine | None = None
_sync_engine: Engine | None = None


def _db_url() -> URL:
    return URL.create(
        drivername="postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )


def build_async_engine() -> AsyncEngine:
    """Construit l'AsyncEngine SQLAlchemy (driver psycopg3, async).

    Paramètres pool alignés sur l'AsyncConnectionPool psycopg :
    - `pool_size = db_pool_min` : connexions persistantes
    - `max_overflow = db_pool_max - db_pool_min` : connexions
      supplémentaires sous charge, fermées au retour
    - `pool_pre_ping = True` : détecte les connexions perdues
      (timeout réseau, reset SGBD) avant de les remettre en service
    """
    return create_async_engine(
        _db_url(),
        pool_size=settings.db_pool_min,
        max_overflow=settings.db_pool_max - settings.db_pool_min,
        pool_pre_ping=True,
    )


def build_sync_engine() -> Engine:
    """Construit l'Engine SQLAlchemy synchrone (driver psycopg3).

    Utilisé par le pipeline (`run_pipeline.py` et phases lancées en
    sous-processus) et les scripts CLI sync. Mêmes paramètres pool
    que l'AsyncEngine : utile quand un script ouvre plusieurs
    connexions en parallèle (ex. fetch_missing_doi qui interroge
    plusieurs sources). Pour un script mono-connexion, le pool est
    silencieusement sous-utilisé sans surcoût notable.
    """
    return create_engine(
        _db_url(),
        pool_size=settings.db_pool_min,
        max_overflow=settings.db_pool_max - settings.db_pool_min,
        pool_pre_ping=True,
    )


def set_async_engine(engine: AsyncEngine | None) -> None:
    """Enregistre (ou désenregistre) l'engine async global. Appelé par le lifespan."""
    global _async_engine
    _async_engine = engine


def get_async_engine() -> AsyncEngine:
    """Retourne l'engine async global. RuntimeError si non initialisé."""
    if _async_engine is None:
        raise RuntimeError(
            "Async engine not initialized — FastAPI lifespan must run before any request"
        )
    return _async_engine


def set_sync_engine(engine: Engine | None) -> None:
    """Enregistre (ou désenregistre) l'engine sync global."""
    global _sync_engine
    _sync_engine = engine


def get_sync_engine() -> Engine:
    """Retourne l'engine sync global, en le construisant à la demande.

    Contrairement à l'async (qui est initialisé par le lifespan FastAPI),
    le sync est instanciable à la volée — utile pour les scripts CLI
    et le pipeline qui n'ont pas de cycle de vie applicatif.
    """
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = build_sync_engine()
    return _sync_engine
