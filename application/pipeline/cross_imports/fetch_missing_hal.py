"""Orchestrateurs du fetch des entrées HAL manquantes.

Deux pistes distinctes, chacune son orchestrateur, partageant un runner async :

- `fetch_missing_hal_by_id` : hal-ids repérés par OpenAlex et ScanR (absents du staging HAL), requête Solr `halId_s`.
- `fetch_missing_hal_by_nnt` : NNT de thèses soutenues sans document HAL (theses.fr), requête Solr `nntId_s`. Réservé au mode `full` — le gate de mode vit chez le caller (`run_pipeline`).

Les documents ramenés sont marqués `collection = NULL` (hors périmètre UCA), ce qui les distingue des entrées issues du portail ou des collections labo.

Fetch HTTP async (httpx + `asyncio.Semaphore(adapter.max_concurrent)`) ; inserts DB sync sérialisés (`asyncio.Lock` + `asyncio.to_thread`, la `Connection` SA sync n'étant pas thread-safe) ; commits intermédiaires tous les `_COMMIT_EVERY`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.cross_imports.fetch_missing_hal import (
    HalFetchMissingAdapter,
    HalIdRef,
    NntRef,
)

__all__ = ["fetch_missing_hal_by_id", "fetch_missing_hal_by_nnt"]

_COMMIT_EVERY = 50


def _dedup_halid_refs(refs: list[HalIdRef]) -> list[HalIdRef]:
    """Garde la première occurrence de chaque hal_id (ordre OA → ScanR)."""
    seen: set[str] = set()
    out: list[HalIdRef] = []
    for ref in refs:
        if ref.hal_id not in seen:
            seen.add(ref.hal_id)
            out.append(ref)
    return out


async def _fetch_refs_async[Ref](
    refs: Sequence[Ref],
    conn: Connection,
    log: logging.Logger,
    *,
    max_concurrent: int,
    delay_s: float,
    fetch_one: Callable[[httpx.AsyncClient, Ref], Awaitable[dict[str, Any] | None]],
    insert_one: Callable[[Connection, Ref, dict[str, Any] | None], tuple[int, int]],
) -> tuple[int, int]:
    """Boucle async partagée : fetch concurrent par ref, puis insert sérialisé.

    `insert_one` retourne `(fetched, not_found)` en incréments (0/1) : la sémantique de comptage propre à chaque piste vit dans la closure appelante. Retourne les totaux `(fetched, not_found)`.
    """
    sem = asyncio.Semaphore(max_concurrent)
    db_lock = asyncio.Lock()
    progress = {"done": 0, "fetched": 0, "not_found": 0}
    total = len(refs)

    async with httpx.AsyncClient() as client:

        async def process_one(ref: Ref) -> None:
            async with sem:
                doc = await fetch_one(client, ref)
                if delay_s:
                    await asyncio.sleep(delay_s)

            async with db_lock:
                fetched, not_found = await asyncio.to_thread(insert_one, conn, ref, doc)
                progress["fetched"] += fetched
                progress["not_found"] += not_found
                progress["done"] += 1
                if progress["done"] % _COMMIT_EVERY == 0:
                    await asyncio.to_thread(conn.commit)
                    log.info(f"  {progress['done']}/{total} — {progress['fetched']} récupérés")

        await asyncio.gather(*(process_one(r) for r in refs))

    await asyncio.to_thread(conn.commit)
    return progress["fetched"], progress["not_found"]


async def fetch_missing_hal_by_id(
    conn: Connection,
    adapter: HalFetchMissingAdapter,
    log: logging.Logger,
    *,
    dry_run: bool = False,
    stats_only: bool = False,
) -> PhaseMetrics:
    """Fetch des documents HAL repérés par hal-id (OpenAlex/ScanR) et absents du staging.

    Phase importable depuis `run_pipeline.py` ; la connexion n'est pas fermée (responsabilité du caller). `new` = documents insérés ; `extras["not_found"]` = hal-ids introuvables côté HAL (marqués `not_found_at`). `total` = hal-ids manquants à traiter (dédupliqués OA + ScanR).
    """
    adapter.configure(conn)

    refs_oa = adapter.find_halid_refs_from_openalex(conn)
    log.info("%d halIds OpenAlex absents de staging_hal", len(refs_oa))
    refs_scanr = adapter.find_halid_refs_from_scanr(conn)
    log.info("%d halIds ScanR absents de staging_hal", len(refs_scanr))

    missing = _dedup_halid_refs(refs_oa + refs_scanr)
    log.info("%d halIds manquants au total (après déduplication)", len(missing))

    metrics = PhaseMetrics(seen=len(missing))
    if stats_only or not missing:
        return metrics

    if dry_run:
        log.info("[DRY RUN] %d documents HAL à télécharger (par halId) :", len(missing))
        for ref in missing[:10]:
            log.info("  [%s] %s → %s", ref.source, ref.foreign_id, ref.hal_id)
        if len(missing) > 10:
            log.info("  ... et %d autres", len(missing) - 10)
        return metrics

    def _insert(conn: Connection, ref: HalIdRef, doc: dict[str, Any] | None) -> tuple[int, int]:
        found = adapter.insert_halid_result(conn, ref.hal_id, doc)
        return (1, 0) if found else (0, 1)

    fetched, not_found = await _fetch_refs_async(
        missing,
        conn,
        log,
        max_concurrent=adapter.max_concurrent,
        delay_s=adapter.delay_s,
        fetch_one=lambda client, ref: adapter.fetch_by_halid(client, ref.hal_id),
        insert_one=_insert,
    )
    metrics.add(new=fetched, not_found=not_found)
    log.info("hal-id : %d récupérés, %d introuvables", fetched, not_found)
    return metrics


async def fetch_missing_hal_by_nnt(
    conn: Connection,
    adapter: HalFetchMissingAdapter,
    log: logging.Logger,
    *,
    dry_run: bool = False,
    stats_only: bool = False,
) -> PhaseMetrics:
    """Fetch des documents HAL de thèses soutenues repérées par NNT (theses.fr).

    Phase importable depuis `run_pipeline.py` ; la connexion n'est pas fermée. `new` = documents insérés ; `extras["not_found"]` = NNT absents de HAL. `total` = NNT (thèses soutenues) sans document HAL.
    """
    adapter.configure(conn)

    nnt_refs = adapter.find_nnt_refs_from_theses(conn)
    log.info("%d NNT (thèses soutenues) sans HAL", len(nnt_refs))

    metrics = PhaseMetrics(seen=len(nnt_refs))
    if stats_only or not nnt_refs:
        return metrics

    if dry_run:
        log.info("[DRY RUN] %d documents HAL à chercher (par NNT) :", len(nnt_refs))
        for ref in nnt_refs[:10]:
            log.info("  [nnt] %s → NNT=%s", ref.theses_id, ref.nnt)
        if len(nnt_refs) > 10:
            log.info("  ... et %d autres", len(nnt_refs) - 10)
        return metrics

    def _insert(conn: Connection, ref: NntRef, doc: dict[str, Any] | None) -> tuple[int, int]:
        api_found, inserted = adapter.insert_nnt_result(conn, ref.nnt, doc)
        return (1 if inserted else 0, 0 if api_found else 1)

    fetched, not_found = await _fetch_refs_async(
        nnt_refs,
        conn,
        log,
        max_concurrent=adapter.max_concurrent,
        delay_s=adapter.delay_s,
        fetch_one=lambda client, ref: adapter.fetch_by_nnt(client, ref.nnt),
        insert_one=_insert,
    )
    metrics.add(new=fetched, not_found=not_found)
    log.info("NNT : %d récupérés, %d absents de HAL", fetched, not_found)
    return metrics
