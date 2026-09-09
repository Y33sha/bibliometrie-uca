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
from application.ports.pipeline.fetch_missing.hal import (
    HalFetchMissingAdapter,
    HalIdRef,
    NntRef,
)
from domain.types import JsonValue

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
    libelle: str,
    max_concurrent: int,
    delay_s: float,
    fetch_one: Callable[[httpx2.AsyncClient, Ref], Awaitable[Mapping[str, JsonValue] | None]],
    insert_one: Callable[[Connection, Ref, Mapping[str, JsonValue] | None], tuple[int, int]],
) -> tuple[int, int]:
    """Fetch concurrent puis insert sérialisé, via `run_fetch_pool`.

    `insert_one` retourne `(fetched, not_found)` en incréments (0/1) : la sémantique de comptage propre à chaque piste vit dans la closure appelante. Retourne les totaux `(fetched, not_found)`.
    """
    counts = {"fetched": 0, "not_found": 0, "done": 0}
    total = len(refs)

    async def _fetch(client: httpx2.AsyncClient, ref: Ref) -> Mapping[str, JsonValue] | None:
        doc = await fetch_one(client, ref)
        if delay_s:
            await asyncio.sleep(delay_s)
        return doc

    with progression(total, libelle, log, compte_retenus=True) as avancement:

        def _write(conn: Connection, ref: Ref, doc: Mapping[str, JsonValue] | None) -> None:
            fetched, not_found = insert_one(conn, ref, doc)
            counts["fetched"] += fetched
            counts["not_found"] += not_found
            counts["done"] += 1
            avancement.avance()
            avancement.retient(fetched)

        await run_fetch_pool(
            refs,
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
    *,
    dry_run: bool = False,
    stats_only: bool = False,
) -> PhaseMetrics:
    """Fetch des documents HAL repérés par hal-id (OpenAlex/ScanR) et absents du staging.

    `new` = documents insérés ; `extras["not_found"]` = hal-ids introuvables côté HAL (marqués `not_found_at`). `total` = hal-ids manquants à traiter (dédupliqués OA + ScanR).
    """
    adapter.configure(conn)

    refs_oa = adapter.find_halid_refs_from_openalex(conn)
    refs_scanr = adapter.find_halid_refs_from_scanr(conn)

    missing = _dedup_halid_refs(refs_oa + refs_scanr)
    attendus = len(missing)

    metrics = PhaseMetrics(seen=attendus)
    if stats_only:
        return metrics
    if not missing:
        log.info("%sRien à faire", DERNIERE_BRANCHE)
        return metrics

    if dry_run:
        log.info("[DRY RUN] %d documents HAL à télécharger (par halId) :", len(missing))
        for ref in missing[:10]:
            log.info("  [%s] %s → %s", ref.source, ref.foreign_id, ref.hal_id)
        if len(missing) > 10:
            log.info("  ... et %d autres", len(missing) - 10)
        return metrics

    def _insert(
        conn: Connection, ref: HalIdRef, doc: Mapping[str, JsonValue] | None
    ) -> tuple[int, int]:
        found = adapter.insert_halid_result(conn, ref.hal_id, doc)
        return (1, 0) if found else (0, 1)

    fetched, not_found = await _fetch_refs_async(
        missing,
        conn,
        log,
        libelle=f"{DERNIERE_BRANCHE}HAL",
        max_concurrent=adapter.max_concurrent,
        delay_s=adapter.delay_s,
        fetch_one=lambda client, ref: adapter.fetch_by_halid(client, ref.hal_id),
        insert_one=_insert,
    )
    metrics.add(new=fetched, not_found=not_found)
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

    `new` = documents insérés ; `extras["not_found"]` = NNT absents de HAL. `total` = NNT (thèses soutenues) sans document HAL.
    """
    adapter.configure(conn)

    nnt_refs = adapter.find_nnt_refs_from_theses(conn)
    attendues = len(nnt_refs)

    metrics = PhaseMetrics(seen=attendues)
    if stats_only:
        return metrics
    if not nnt_refs:
        log.info("%saucune thèse soutenue sans document HAL", DERNIERE_BRANCHE)
        return metrics

    if dry_run:
        log.info("[DRY RUN] %d documents HAL à chercher (par NNT) :", len(nnt_refs))
        for ref in nnt_refs[:10]:
            log.info("  [nnt] %s → NNT=%s", ref.theses_id, ref.nnt)
        if len(nnt_refs) > 10:
            log.info("  ... et %d autres", len(nnt_refs) - 10)
        return metrics

    def _insert(
        conn: Connection, ref: NntRef, doc: Mapping[str, JsonValue] | None
    ) -> tuple[int, int]:
        api_found, inserted = adapter.insert_nnt_result(conn, ref.nnt, doc)
        return (1 if inserted else 0, 0 if api_found else 1)

    fetched, not_found = await _fetch_refs_async(
        nnt_refs,
        conn,
        log,
        libelle=f"{DERNIERE_BRANCHE}HAL",
        max_concurrent=adapter.max_concurrent,
        delay_s=adapter.delay_s,
        fetch_one=lambda client, ref: adapter.fetch_by_nnt(client, ref.nnt),
        insert_one=_insert,
    )
    metrics.add(new=fetched, not_found=not_found)
    return metrics
