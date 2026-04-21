"""Dépendances async FastAPI : curseur async via AsyncConnectionPool (§2.12).

Parallèle à `interfaces/api/deps.get_cursor` pendant la migration. À
utiliser dans les routers migrés vers async.

`pool.connection()` gère automatiquement commit (succès) / rollback
(exception) et la restitution au pool, cf. psycopg_pool.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from infrastructure.db.async_connection import get_async_pool


@asynccontextmanager
async def get_async_cursor() -> AsyncIterator[tuple[Any, Any]]:
    pool = get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            yield cur, conn
