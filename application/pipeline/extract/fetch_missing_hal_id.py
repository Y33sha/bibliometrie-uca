"""Orchestrateur du fetch des entrées HAL manquantes.

Trois sources de halIds (et NNT theses.fr) :
- OpenAlex : `primary_location` pointant vers `hal.science/hal-XXXXX`
- ScanR : `externalIds` contenant un identifiant de type `hal`
- theses.fr (via NNT) : thèses soutenues avec NNT mais sans document HAL

Quand un halId (ou un NNT) n'est pas dans le staging HAL, on le
télécharge via l'API HAL. Ces entrées sont marquées `collection = NULL`
(hors périmètre UCA), ce qui les distingue des entrées issues du
portail ou des collections labo.

Fetch HTTP async via httpx + `asyncio.Semaphore(adapter.max_concurrent)`
pour saturer le rate-limit toléré sans le dépasser. Les inserts DB
restent sync (`Connection` SA) et sont sérialisés via `asyncio.Lock`
+ `asyncio.to_thread`.

Modes pipeline : `full` interroge aussi les NNT theses sans HAL ;
`weekly`/`daily` les ignorent (volume trop large pour run incrémental).
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.fetch_missing_hal_id import (
    HalFetchMissingAdapter,
    HalIdRef,
    NntRef,
)


def _dedup_halid_refs(refs: list[HalIdRef]) -> list[HalIdRef]:
    """Garde la première occurrence de chaque hal_id (ordre OA → ScanR)."""
    seen: set[str] = set()
    out: list[HalIdRef] = []
    for ref in refs:
        if ref.hal_id not in seen:
            seen.add(ref.hal_id)
            out.append(ref)
    return out


async def _fetch_by_halid_async(
    adapter: HalFetchMissingAdapter,
    refs: list[HalIdRef],
    conn: Connection,
    log: logging.Logger,
) -> tuple[int, int]:
    """Fetch en parallèle par halId. Retourne (fetched, not_found)."""
    sem = asyncio.Semaphore(adapter.max_concurrent)
    db_lock = asyncio.Lock()
    progress = {"done": 0, "fetched": 0, "not_found": 0}
    total = len(refs)

    async with httpx.AsyncClient() as client:

        async def process_one(ref: HalIdRef) -> None:
            async with sem:
                doc = await adapter.fetch_by_halid(client, ref.hal_id)
                if adapter.delay_s:
                    await asyncio.sleep(adapter.delay_s)

            async with db_lock:
                found = await asyncio.to_thread(adapter.insert_halid_result, conn, ref.hal_id, doc)
                if found:
                    progress["fetched"] += 1
                else:
                    progress["not_found"] += 1

                progress["done"] += 1
                if progress["done"] % 50 == 0:
                    await asyncio.to_thread(conn.commit)
                    log.info(f"  {progress['done']}/{total} — {progress['fetched']} récupérés")

        await asyncio.gather(*(process_one(r) for r in refs))

    await asyncio.to_thread(conn.commit)
    return progress["fetched"], progress["not_found"]


async def _fetch_by_nnt_async(
    adapter: HalFetchMissingAdapter,
    refs: list[NntRef],
    conn: Connection,
    log: logging.Logger,
) -> tuple[int, int]:
    """Fetch en parallèle par NNT. Retourne (fetched, not_found)."""
    sem = asyncio.Semaphore(adapter.max_concurrent)
    db_lock = asyncio.Lock()
    progress = {"done": 0, "fetched": 0, "not_found": 0}
    total = len(refs)

    async with httpx.AsyncClient() as client:

        async def process_one(ref: NntRef) -> None:
            async with sem:
                doc = await adapter.fetch_by_nnt(client, ref.nnt)
                if adapter.delay_s:
                    await asyncio.sleep(adapter.delay_s)

            async with db_lock:
                api_found, inserted = await asyncio.to_thread(
                    adapter.insert_nnt_result, conn, ref.nnt, doc
                )
                if inserted:
                    progress["fetched"] += 1
                if not api_found:
                    progress["not_found"] += 1

                progress["done"] += 1
                if progress["done"] % 50 == 0:
                    await asyncio.to_thread(conn.commit)
                    log.info(
                        f"  {progress['done']}/{total} — "
                        f"{progress['fetched']} récupérés, "
                        f"{progress['not_found']} absents de HAL"
                    )

        await asyncio.gather(*(process_one(r) for r in refs))

    await asyncio.to_thread(conn.commit)
    return progress["fetched"], progress["not_found"]


async def fetch_missing_hal_ids(
    conn: Connection,
    adapter: HalFetchMissingAdapter,
    log: logging.Logger,
    *,
    mode: str = "full",
    dry_run: bool = False,
    stats_only: bool = False,
) -> PhaseMetrics:
    """Récupère les entrées HAL manquantes via OpenAlex / ScanR / NNT theses.

    Phase importable depuis `run_pipeline.py` ; la connexion n'est pas
    fermée (responsabilité du caller). `new` compte les documents HAL
    insérés ; `extras["not_found"]` ceux marqués not_found (introuvables
    côté HAL). `total` = nombre de halIds manquants à traiter.
    """
    adapter.configure(conn)

    log.info("Recherche des halIds référencés par OpenAlex (toutes locations)...")
    hal_refs_oa = adapter.find_halid_refs_from_openalex(conn)
    log.info(f"  {len(hal_refs_oa)} halIds OpenAlex absents de staging_hal")

    log.info("Recherche des HAL IDs dans ScanR...")
    hal_refs_scanr = adapter.find_halid_refs_from_scanr(conn)
    log.info(f"  {len(hal_refs_scanr)} halIds ScanR absents de staging_hal")

    if mode == "full":
        log.info("Recherche des NNT sans document HAL...")
        nnt_refs = adapter.find_nnt_refs_from_theses(conn)
        log.info(f"  {len(nnt_refs)} NNT (thèses soutenues) sans HAL")
    else:
        nnt_refs = []
        log.info("NNT ignoré en mode %s", mode)

    missing = _dedup_halid_refs(hal_refs_oa + hal_refs_scanr)
    log.info(f"  {len(missing)} halIds manquants au total (après déduplication)")

    metrics = PhaseMetrics(total=len(missing) + len(nnt_refs))

    if stats_only:
        log.info("--- Statistiques ---")
        log.info(f"  halIds OA absents de staging_hal : {len(hal_refs_oa)}")
        log.info(f"  halIds ScanR absents de staging_hal : {len(hal_refs_scanr)}")
        log.info(f"  NNT sans HAL : {len(nnt_refs)}")
        log.info(f"  Total halIds manquants (dédupliqués) : {len(missing)}")
        return metrics

    if not missing and not nnt_refs:
        log.info("Rien à faire.")
        return metrics

    if dry_run:
        if missing:
            log.info(f"[DRY RUN] {len(missing)} documents HAL à télécharger (par halId) :")
            for hal_ref in missing[:10]:
                log.info(f"  [{hal_ref.source}] {hal_ref.foreign_id} → {hal_ref.hal_id}")
            if len(missing) > 10:
                log.info(f"  ... et {len(missing) - 10} autres")
        if nnt_refs:
            log.info(f"[DRY RUN] {len(nnt_refs)} documents HAL à chercher (par NNT) :")
            for nnt_ref in nnt_refs[:10]:
                log.info(f"  [nnt] {nnt_ref.theses_id} → NNT={nnt_ref.nnt}")
            if len(nnt_refs) > 10:
                log.info(f"  ... et {len(nnt_refs) - 10} autres")
        return metrics

    fetched = 0
    not_found = 0

    if missing:
        log.info(f"\n--- Fetch par halId ({len(missing)} documents) ---")
        f1, nf1 = await _fetch_by_halid_async(adapter, missing, conn, log)
        fetched += f1
        not_found += nf1

    if nnt_refs:
        log.info(f"\n--- Fetch par NNT ({len(nnt_refs)} thèses) ---")
        f2, nf2 = await _fetch_by_nnt_async(adapter, nnt_refs, conn, log)
        fetched += f2
        not_found += nf2
        log.info(f"  NNT : {f2} récupérés, {nf2} absents de HAL")

    metrics.add(new=fetched, not_found=not_found)
    log.info(f"\nTerminé : {fetched} récupérés, {not_found} introuvables")
    log.info("Relancer normalize_hal.py pour les integrer")
    return metrics


__all__ = ["fetch_missing_hal_ids"]
