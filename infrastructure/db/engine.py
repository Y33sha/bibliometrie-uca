"""AsyncEngine SQLAlchemy basé sur le driver psycopg3.

Cohabite avec le pool psycopg `infrastructure/db/async_connection.py`
pendant la phase de migration (chantier
docs/chantiers/sqlalchemy-core-adoption.md). Le pool psycopg est
progressivement remplacé : tant qu'il existe encore, les deux
ouvrent leur propre connexion. À terme (Phase 4 du chantier), seul
l'AsyncEngine SQLAlchemy subsistera.

Le driver sous-jacent reste psycopg3 (URL
`postgresql+psycopg://...`), donc aucun changement côté DB et les
features psycopg (server-side cursors, COPY, etc.) restent
accessibles via `AsyncConnection.driver_connection` si besoin.
"""

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from infrastructure.settings import settings

_async_engine: AsyncEngine | None = None


def build_async_engine() -> AsyncEngine:
    """Construit l'AsyncEngine SQLAlchemy (driver psycopg3, async).

    Paramètres pool alignés sur l'AsyncConnectionPool psycopg :
    - `pool_size = db_pool_min` : connexions persistantes
    - `max_overflow = db_pool_max - db_pool_min` : connexions
      supplémentaires sous charge, fermées au retour
    - `pool_pre_ping = True` : détecte les connexions perdues
      (timeout réseau, reset SGBD) avant de les remettre en service
    """
    url = URL.create(
        drivername="postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )
    return create_async_engine(
        url,
        pool_size=settings.db_pool_min,
        max_overflow=settings.db_pool_max - settings.db_pool_min,
        pool_pre_ping=True,
    )


def set_async_engine(engine: AsyncEngine | None) -> None:
    """Enregistre (ou désenregistre) l'engine global. Appelé par le lifespan."""
    global _async_engine
    _async_engine = engine


def get_async_engine() -> AsyncEngine:
    """Retourne l'engine global. RuntimeError si non initialisé."""
    if _async_engine is None:
        raise RuntimeError(
            "Async engine not initialized — FastAPI lifespan must run before any request"
        )
    return _async_engine
