"""Dépendances async FastAPI : curseur async via AsyncConnectionPool,
et câblage des adapters sortants vers leurs ports (composition root API).

`pool.connection()` gère automatiquement commit (succès) / rollback
(exception) et la restitution au pool, cf. psycopg_pool.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from application.ports.perimeter import AsyncPerimeterQueries
from infrastructure.db.async_connection import get_async_pool
from infrastructure.db.queries.perimeter import PgAsyncPerimeterQueries


@asynccontextmanager
async def get_async_cursor() -> AsyncIterator[tuple[Any, Any]]:
    pool = get_async_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            yield cur, conn


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
