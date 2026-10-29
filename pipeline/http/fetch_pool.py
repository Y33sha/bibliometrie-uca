"""Pool de workers pour les tâches qui interrogent une source HTTP puis écrivent en base.

Les workers partagent un client `httpx2` et tirent les éléments d'un même itérateur : un fetch lent occupe seulement son worker. Les écritures passent sous un verrou : la `Connection` SQLAlchemy synchrone n'est pas thread-safe, et `asyncio.to_thread` s'exécute dans un pool de threads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

import httpx2
from sqlalchemy import Connection

from pipeline.http.circuit_breaker import source_tripped
from pipeline.http.tls import tls_context


async def run_fetch_pool[Item, Fetched](
    items: Sequence[Item],
    conn: Connection,
    *,
    max_concurrent: int,
    commit_every: int,
    fetch: Callable[[httpx2.AsyncClient, Item], Awaitable[Fetched]],
    write: Callable[[Connection, Item, Fetched], None],
    prepare: Callable[[Connection, Item], Item] | None = None,
) -> None:
    """Traite `items` avec `max_concurrent` workers : `fetch` asynchrone et concurrent, puis `write` synchrone et sérialisé, sans commit. Le pool commite tous les `commit_every` éléments, et à la fin. Il s'arrête quand le circuit-breaker de la source coupe.

    `prepare`, facultatif, complète un élément par une lecture en base avant son fetch, sous le verrou des écritures.
    """
    db_lock = asyncio.Lock()
    item_iter = iter(items)
    done = 0

    async with httpx2.AsyncClient(verify=tls_context()) as client:

        async def worker() -> None:
            nonlocal done
            for item in item_iter:
                if source_tripped():
                    return
                if prepare is not None:
                    async with db_lock:
                        item = await asyncio.to_thread(prepare, conn, item)
                fetched = await fetch(client, item)
                async with db_lock:
                    await asyncio.to_thread(write, conn, item, fetched)
                    done += 1
                    if done % commit_every == 0:
                        await asyncio.to_thread(conn.commit)

        await asyncio.gather(*(worker() for _ in range(max_concurrent)))

    await asyncio.to_thread(conn.commit)
