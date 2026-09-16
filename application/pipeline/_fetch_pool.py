"""Pool de workers pour les phases qui fetchent une source HTTP puis écrivent en base.

Motif partagé par les orchestrateurs async du pipeline (phase `fetch_missing` par hal-id, NNT et DOI, re-fetch des works tronqués) : un client `httpx2` partagé, un pool borné de workers qui se répartissent les items via un itérateur commun (aucune barrière — un fetch lent n'occupe que son propre worker, les autres continuent), des écritures sérialisées sous un lock (la `Connection` SA sync n'est pas thread-safe, or `asyncio.to_thread` s'exécute dans un pool de threads), et un commit tous les `commit_every` items plus un commit final.

`write` ne commite pas : c'est cet helper qui porte le commit, par lot. `should_continue`
permet un arrêt anticipé (coupe-circuit d'une source indisponible) : dès qu'il rend `False`,
les workers cessent de tirer de nouveaux items.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence

import httpx2
from sqlalchemy import Connection


class RequestPace:
    """Plafond de débit commun à des requêtes simultanées : les départs sont réservés l'un après l'autre, espacés de `1 / max_per_second` seconde.

    Une pause propre à chaque worker donne un débit qui dépend du temps de réponse de la source ; ce rythme partagé le borne quelle que soit la concurrence.

    Un worker que l'ordonnancement retarde part après sa réservation, jamais avant : le nombre de départs sur une durée reste borné, même quand deux d'entre eux se suivent de près après une pause de la boucle d'événements.
    """

    def __init__(self, max_per_second: float) -> None:
        self._interval_s = 1 / max_per_second
        self._next_start = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """Attend le prochain départ autorisé et le réserve."""
        async with self._lock:
            now = time.monotonic()
            start = max(now, self._next_start)
            self._next_start = start + self._interval_s
        if start > now:
            await asyncio.sleep(start - now)


async def run_fetch_pool[Item, Fetched](
    items: Sequence[Item],
    conn: Connection,
    *,
    max_concurrent: int,
    commit_every: int,
    fetch: Callable[[httpx2.AsyncClient, Item], Awaitable[Fetched]],
    write: Callable[[Connection, Item, Fetched], None],
    should_continue: Callable[[], bool] = lambda: True,
) -> None:
    """Traite `items` par un pool de `max_concurrent` workers : `fetch` async concurrent
    puis `write` sync sérialisé, commit tous les `commit_every` items."""
    db_lock = asyncio.Lock()
    item_iter = iter(items)
    done = 0

    async with httpx2.AsyncClient() as client:

        async def worker() -> None:
            nonlocal done
            for item in item_iter:
                if not should_continue():
                    return
                fetched = await fetch(client, item)
                async with db_lock:
                    await asyncio.to_thread(write, conn, item, fetched)
                    done += 1
                    if done % commit_every == 0:
                        await asyncio.to_thread(conn.commit)

        await asyncio.gather(*(worker() for _ in range(max_concurrent)))

    await asyncio.to_thread(conn.commit)
