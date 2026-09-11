"""Orchestrateurs du fetch des entrées HAL manquantes.

Deux pistes distinctes, chacune son orchestrateur, partageant un runner async :

- `fetch_missing_hal_by_id` : hal-ids repérés par OpenAlex et ScanR (absents du staging HAL), requête Solr `halId_s`.
- `fetch_missing_hal_by_nnt` : NNT de thèses soutenues sans document HAL (theses.fr), requête Solr `nntId_s`. Réservé au mode `full`.

Fetch HTTP async via `run_fetch_pool` : pool de `adapter.max_concurrent` workers, inserts DB sérialisés, commits tous les `_COMMIT_EVERY`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence

import httpx2
from sqlalchemy import Connection

from application.pipeline._fetch_pool import run_fetch_pool
from application.pipeline.libelles import DERNIERE_BRANCHE
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import progression
from application.ports.pipeline.fetch_missing.hal import HalFetchMissingAdapter
from domain.types import JsonValue

__all__ = ["fetch_missing_hal_by_id", "fetch_missing_hal_by_nnt"]

_COMMIT_EVERY = 50


async def _fetch_ids_async(
    ids: Sequence[str],
    conn: Connection,
    log: logging.Logger,
    *,
    libelle: str,
    max_concurrent: int,
    delay_s: float,
    fetch_one: Callable[[httpx2.AsyncClient, str], Awaitable[Mapping[str, JsonValue] | None]],
    insert_one: Callable[[Connection, str, Mapping[str, JsonValue] | None], tuple[int, int]],
) -> tuple[int, int]:
    """Fetch concurrent puis insert sérialisé, via `run_fetch_pool`.

    `insert_one` retourne `(fetched, not_found)` en incréments (0/1) : la sémantique de comptage propre à chaque piste vit dans la closure appelante. Retourne les totaux `(fetched, not_found)`.
    """
    counts = {"fetched": 0, "not_found": 0, "done": 0}
    total = len(ids)

    async def _fetch(client: httpx2.AsyncClient, identifier: str) -> Mapping[str, JsonValue] | None:
        doc = await fetch_one(client, identifier)
        if delay_s:
            await asyncio.sleep(delay_s)
        return doc

    with progression(total, libelle, log, compte_retenus=True) as avancement:

        def _write(conn: Connection, identifier: str, doc: Mapping[str, JsonValue] | None) -> None:
            fetched, not_found = insert_one(conn, identifier, doc)
            counts["fetched"] += fetched
            counts["not_found"] += not_found
            counts["done"] += 1
            avancement.avance()
            avancement.retient(fetched)

        await run_fetch_pool(
            ids,
            conn,
            max_concurrent=max_concurrent,
            commit_every=_COMMIT_EVERY,
            fetch=_fetch,
            write=_write,
        )
    return counts["fetched"], counts["not_found"]


async def fetch_missing_hal_by_id(
    conn: Connection,
    adapter: HalFetchMissingAdapter,
    log: logging.Logger,
) -> PhaseMetrics:
    """Fetch des documents HAL repérés par hal-id (OpenAlex/ScanR) et absents du staging.

    `new` = documents insérés ; `extras["not_found"]` = hal-ids introuvables côté HAL (marqués `not_found_at`). `total` = hal-ids manquants à traiter.
    """
    adapter.configure(conn)

    hal_ids = adapter.find_missing_hal_ids(conn)

    metrics = PhaseMetrics(seen=len(hal_ids))
    if not hal_ids:
        log.info("%sRien à faire", DERNIERE_BRANCHE)
        return metrics

    def _insert(
        conn: Connection, hal_id: str, doc: Mapping[str, JsonValue] | None
    ) -> tuple[int, int]:
        found = adapter.insert_halid_result(conn, hal_id, doc)
        return (1, 0) if found else (0, 1)

    fetched, not_found = await _fetch_ids_async(
        hal_ids,
        conn,
        log,
        libelle=f"{DERNIERE_BRANCHE}HAL",
        max_concurrent=adapter.max_concurrent,
        delay_s=adapter.delay_s,
        fetch_one=adapter.fetch_by_halid,
        insert_one=_insert,
    )
    metrics.add(new=fetched, not_found=not_found)
    return metrics


async def fetch_missing_hal_by_nnt(
    conn: Connection,
    adapter: HalFetchMissingAdapter,
    log: logging.Logger,
) -> PhaseMetrics:
    """Fetch des documents HAL de thèses soutenues repérées par NNT (theses.fr).

    `new` = documents insérés ; `extras["not_found"]` = NNT absents de HAL. `total` = NNT (thèses soutenues) sans document HAL.
    """
    adapter.configure(conn)

    nnts = adapter.find_missing_nnts(conn)

    metrics = PhaseMetrics(seen=len(nnts))
    if not nnts:
        log.info("%sRien à faire", DERNIERE_BRANCHE)
        return metrics

    def _insert(conn: Connection, nnt: str, doc: Mapping[str, JsonValue] | None) -> tuple[int, int]:
        api_found, inserted = adapter.insert_nnt_result(conn, nnt, doc)
        return (1 if inserted else 0, 0 if api_found else 1)

    fetched, not_found = await _fetch_ids_async(
        nnts,
        conn,
        log,
        libelle=f"{DERNIERE_BRANCHE}HAL",
        max_concurrent=adapter.max_concurrent,
        delay_s=adapter.delay_s,
        fetch_one=adapter.fetch_by_nnt,
        insert_one=_insert,
    )
    metrics.add(new=fetched, not_found=not_found)
    return metrics
