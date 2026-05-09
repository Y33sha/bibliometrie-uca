"""Engine SQLAlchemy synchrone basé sur le driver psycopg3.

Un seul Engine sync utilisé par toute l'application :
- L'API FastAPI consomme cet engine via `db_conn_sync` (les routes `def`
  tournent dans le threadpool Starlette).
- Le pipeline et les scripts CLI ouvrent leurs propres connexions via
  `engine.begin()` / `engine.connect()`.

Le driver `postgresql+psycopg` permet d'accéder aux features psycopg3
(server-side cursors, COPY) via `Connection.connection.driver_connection`
si besoin.
"""

from sqlalchemy import URL, Engine, create_engine

from infrastructure.settings import settings

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


def build_sync_engine() -> Engine:
    """Construit l'Engine SQLAlchemy synchrone (driver psycopg3).

    Utilisé par toute la surface (API, pipeline, CLI). Paramètres pool :
    - `pool_size = db_pool_min` : connexions persistantes
    - `max_overflow = db_pool_max - db_pool_min` : connexions
      supplémentaires sous charge, fermées au retour
    - `pool_pre_ping = True` : détecte les connexions perdues
      (timeout réseau, reset SGBD) avant de les remettre en service
    """
    return create_engine(
        _db_url(),
        pool_size=settings.db_pool_min,
        max_overflow=settings.db_pool_max - settings.db_pool_min,
        pool_pre_ping=True,
    )


def set_sync_engine(engine: Engine | None) -> None:
    """Enregistre (ou désenregistre) l'engine sync global."""
    global _sync_engine
    _sync_engine = engine


def get_sync_engine() -> Engine:
    """Retourne l'engine sync global, en le construisant à la demande.

    L'API initialise l'engine au démarrage via le lifespan, mais les
    scripts CLI / le pipeline n'ont pas de cycle de vie applicatif :
    ils déclenchent la construction lazy au premier appel.
    """
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = build_sync_engine()
    return _sync_engine
