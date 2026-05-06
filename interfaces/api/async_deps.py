"""Dépendances async FastAPI : curseur async via AsyncConnectionPool,
et câblage des adapters sortants vers leurs ports (composition root API).

`pool.connection()` gère automatiquement commit (succès) / rollback
(exception) et la restitution au pool, cf. psycopg_pool.

`get_sa_connection()` est l'équivalent SQLAlchemy : ouvre une
AsyncConnection sur l'AsyncEngine, dans une transaction commit
(succès) / rollback (exception). À utiliser par les modules migrés
en SQLAlchemy Core (chantier sqlalchemy-core-adoption). Cohabite
avec `get_async_cursor()` pendant la migration ; le pool psycopg
disparaîtra en Phase 4.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from application.ports.perimeter import AsyncPerimeterQueries
from infrastructure.db.async_connection import get_async_pool
from infrastructure.db.engine import get_async_engine
from infrastructure.db.queries.perimeter import PgAsyncPerimeterQueries


@asynccontextmanager
async def get_async_cursor() -> AsyncIterator[tuple[Any, Any]]:
    pool = get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            yield cur, conn


@asynccontextmanager
async def get_sa_connection() -> AsyncIterator[AsyncConnection]:
    """AsyncConnection SQLAlchemy en transaction commit/rollback auto.

    Pour les modules migrés en SQLAlchemy Core. Le `engine.begin()`
    ouvre une transaction qui commit si pas d'exception, rollback
    sinon — équivalent au pattern de `pool.connection()` côté psycopg.
    """
    engine = get_async_engine()
    async with engine.begin() as conn:
        yield conn


# ── Câblage des adapters sortants ──

# PgAsyncPerimeterQueries est sans état (le curseur est passé aux
# méthodes), donc un singleton par processus suffit. Les routers
# reçoivent l'objet via le port `AsyncPerimeterQueries` sans connaître
# l'implémentation concrète.
_perimeter_queries_singleton: AsyncPerimeterQueries = PgAsyncPerimeterQueries()


def get_perimeter_queries() -> AsyncPerimeterQueries:
    """Retourne l'implémentation enregistrée de `AsyncPerimeterQueries`."""
    return _perimeter_queries_singleton


# ----- Perimeter root -----

_root_structure_id: int | None = None


async def get_root_structure_id() -> int:
    """Retourne l'ID de la structure racine du périmètre principal.

    Lit perimeters.structure_ids[1] pour le périmètre configuré dans
    config.perimeter_persons. Valeur cachée après le premier appel
    (lookup unique par vie du processus).
    """
    global _root_structure_id
    if _root_structure_id is not None:
        return _root_structure_id
    async with get_async_cursor() as (cur, _):
        await cur.execute("""
            SELECT p.structure_ids[1] AS root_id
            FROM config c
            JOIN perimeters p ON p.code = c.value #>> '{}'
            WHERE c.key = 'perimeter_persons'
        """)
        row = await cur.fetchone()
        if row and row["root_id"]:
            _root_structure_id = row["root_id"]
        else:
            _root_structure_id = 0  # Périmètre non configuré — les filtres APC seront sans effet
    return _root_structure_id
