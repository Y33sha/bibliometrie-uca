"""Pool async psycopg3 pour la surface FastAPI.

Parallèle au pool sync de `interfaces/api/deps.py` (utilisé par le
pipeline et les CLI). Le pool async est ouvert via le lifespan
FastAPI (cf. `interfaces/api/app.py`).
"""

import os

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from infrastructure.settings import settings

_async_pool: AsyncConnectionPool | None = None


def build_async_pool() -> AsyncConnectionPool:
    """Construit le pool async (non ouvert). `await pool.open()` dans le lifespan.

    `prepare_threshold` laissé au défaut psycopg3 (= 5). Une valeur plus
    agressive (1) cache le plan dès le 1er appel mais fait croître le
    cache des prepared statements sans borne sur les requêtes dynamiques
    (facettes/filtres publications, listings paginés) — chaque
    combinaison de filtres = string SQL distincte = entry distincte côté
    Postgres, jamais évincée tant que la connexion vit. À 5, seules les
    requêtes vraiment répétées entrent dans le cache : les hot paths
    (`find_by_doi`, `list publications`) atteignent 5 appels en quelques
    secondes, les variantes rares ne s'accumulent pas.
    """
    db_args = settings.db_args
    if os.environ.get("BIBLIOMETRIE_SANDBOX") == "1":
        db_args["dbname"] = "bibliometrie_sandbox"
    return AsyncConnectionPool(
        conninfo="",
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        kwargs={**db_args, "row_factory": dict_row},
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
