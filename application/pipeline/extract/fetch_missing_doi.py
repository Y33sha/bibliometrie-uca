"""Orchestrateur du fetch des DOI manquants dans une source cible.

Pour chaque DOI présent dans d'autres sources mais absent de la cible,
interroge l'API de la cible et insère le record dans staging.

Le comportement spécifique à chaque source (endpoint, auth, format de
requête/réponse, SQL d'insertion) est délégué à un adapter qui
implémente `AsyncFetchMissingDoiAdapter`
(`application/ports/pipeline/extract/fetch_missing_doi.py`).

Implémentation async (`httpx.AsyncClient` + `asyncio.Semaphore` par
source) pour saturer les rate-limits autorisés. Sur OpenAlex on
mesure environ 18 req/s, soit ×3-4 par rapport à un appel séquentiel
respectant le même quota.

Utilisé par la phase `cross_imports` du pipeline, une fois par source
cible (hal, openalex, wos, scanr, crossref).
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.fetch_missing_doi import (
    AsyncFetchMissingDoiAdapter,
    CrossImportDoisReader,
)

__all__ = ["AsyncFetchMissingDoiAdapter", "CrossImportDoisReader", "run_async"]


async def run_async(
    conn: Connection,
    adapter: AsyncFetchMissingDoiAdapter,
    log: logging.Logger,
    *,
    cross_import_dois_reader: CrossImportDoisReader,
    all_staged: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
) -> PhaseMetrics:
    """Boucle principale : missing DOIs → fetch async → insert.

    Lance les fetchs HTTP en parallèle via `asyncio.gather`, bornés par
    un sémaphore `adapter.max_concurrent` pour respecter le rate-limit
    de l'API. Les inserts DB restent sync, délégués au threadpool via
    `asyncio.to_thread` et sérialisés par un `asyncio.Lock` (la
    `Connection` SA sync n'est pas thread-safe).

    Args:
        conn: `Connection` SA ouverte.
        adapter: instance source-spécifique async.
        log: logger.
        cross_import_dois_reader: callable qui lit en base les DOI
            présents dans d'autres sources et absents de la cible.
        all_staged: si False, ne considère que les DOI issus de rows
            `processed=FALSE` dans les autres sources.
        dry_run: compte et log sans fetch ni insert.
        limit: nombre max de DOI à traiter.

    Returns:
        `PhaseMetrics` : `total` = DOI traités, `new` = inserts effectifs,
        `extras["fetched"]` = records reçus de l'API.
    """
    adapter.configure(conn)

    dois = cross_import_dois_reader(conn, adapter.source_key, all_staged)
    log.info("%d DOI manquants pour %s", len(dois), adapter.source_key)

    if limit:
        dois = dois[:limit]
        log.info("Limité à %d DOI", len(dois))

    if dry_run:
        log.info("Dry-run — rien inséré.")
        return PhaseMetrics(total=len(dois))

    total = len(dois)
    if total == 0:
        return PhaseMetrics()

    batches = [dois[i : i + adapter.batch_size] for i in range(0, total, adapter.batch_size)]

    sem = asyncio.Semaphore(adapter.max_concurrent)
    # Sérialise les inserts : la `Connection` SA sync n'est pas thread-safe,
    # or `asyncio.to_thread` exécute dans un ThreadPoolExecutor partagé.
    db_lock = asyncio.Lock()
    progress = {"processed": 0, "fetched": 0, "inserted": 0}

    async with httpx.AsyncClient() as client:
        request_delay = getattr(adapter, "request_delay_s", 0.0)

        async def process_batch(batch: list[str], batch_idx: int) -> None:
            async with sem:
                try:
                    records = list(await adapter.fetch_async(client, batch))
                except Exception as e:
                    log.error("Erreur sur lot %d (%d DOI) : %s", batch_idx, len(batch), e)
                    records = []
                if request_delay:
                    await asyncio.sleep(request_delay)

            progress["fetched"] += len(records)
            for record in records:
                try:
                    async with db_lock:
                        inserted_one = await asyncio.to_thread(adapter.insert, conn, record)
                    if inserted_one:
                        progress["inserted"] += 1
                except Exception as e:
                    log.warning("Erreur insertion (%s) : %s", adapter.source_key, e)

            progress["processed"] += len(batch)
            if progress["processed"] % 100 == 0 or progress["processed"] >= total:
                duplicates = progress["fetched"] - progress["inserted"]
                log.info(
                    "  %d/%d — %d records (%d nouveaux, %d doublons)",
                    progress["processed"],
                    total,
                    progress["fetched"],
                    progress["inserted"],
                    duplicates,
                )

        await asyncio.gather(*(process_batch(b, i) for i, b in enumerate(batches)))

    duplicates = progress["fetched"] - progress["inserted"]
    log.info(
        "Terminé %s : %d DOI interrogés, %d records (%d nouveaux, %d doublons déjà en staging)",
        adapter.source_key,
        total,
        progress["fetched"],
        progress["inserted"],
        duplicates,
    )
    return PhaseMetrics(
        total=total, new=progress["inserted"], extras={"fetched": progress["fetched"]}
    )
