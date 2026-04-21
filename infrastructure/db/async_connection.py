"""Pool async psycopg3 pour la surface FastAPI (§2.12).

Parallèle au pool sync de `interfaces/api/deps.py` pendant la migration ;
le pool sync reste en place pour le pipeline et les CLI. Le pool async
est ouvert via le lifespan FastAPI (cf. `interfaces/api/app.py`).
"""

import os

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from infrastructure.settings import settings

_async_pool: AsyncConnectionPool | None = None


def build_async_pool() -> AsyncConnectionPool:
    """Construit le pool async (non ouvert). `await pool.open()` dans le lifespan.

    `prepare_threshold=1` : chaque requête est préparée dès le 1er appel
    (défaut psycopg3 = 5). L'API ré-exécute constamment les mêmes
    requêtes type `find_by_doi`, `list publications`, etc. → bénéfice
    immédiat sur le plan d'exécution PostgreSQL et ~20-30 µs économisées
    par requête.
    """
    db_args = settings.db_args
    if os.environ.get("BIBLIOMETRIE_SANDBOX") == "1":
        db_args["dbname"] = "bibliometrie_sandbox"
    return AsyncConnectionPool(
        conninfo="",
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        kwargs={**db_args, "row_factory": dict_row, "prepare_threshold": 1},
        open=False,
    )


def set_async_pool(pool: AsyncConnectionPool | None) -> None:
    """Enregistre (ou désenregistre) le pool global. Appelé par le lifespan."""
    global _async_pool
    _async_pool = pool


def get_async_pool() -> AsyncConnectionPool:
    if _async_pool is None:
        raise RuntimeError(
            "Async pool not initialized — FastAPI lifespan must run before any request"
        )
    return _async_pool
