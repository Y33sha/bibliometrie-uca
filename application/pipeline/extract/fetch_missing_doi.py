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
from collections.abc import Callable

import httpx
from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.pipeline.extract.fetch_missing_doi import (
    AsyncFetchMissingDoiAdapter,
    CrossImportDoisReader,
    is_not_found_marker,
)

__all__ = ["AsyncFetchMissingDoiAdapter", "CrossImportDoisReader", "run_async"]


async def run_async(
    conn: Connection,
    adapter: AsyncFetchMissingDoiAdapter,
    log: logging.Logger,
    *,
    cross_import_dois_reader: CrossImportDoisReader,
    marker_handler: Callable[[Connection, str], None] | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Boucle principale : DOIs → fetch async → insert.

    Lance les fetchs HTTP en parallèle via `asyncio.gather`, bornés par
    un sémaphore `adapter.max_concurrent` pour respecter le rate-limit
    de l'API. Les inserts DB restent sync, délégués au threadpool via
    `asyncio.to_thread` et sérialisés par un `asyncio.Lock` (la
    `Connection` SA sync n'est pas thread-safe).

    Un DOI confirmé absent par la source (réponse vide / 404) revient
    sous forme de sentinelle `not_found_marker`. Routage de la sentinelle :
    - sans `marker_handler` (cross-import) : `insert()` la route vers le
      backoff (`doi_lookups` / stub `staging` Crossref) ;
    - avec `marker_handler` (refresh stale) : appelé `(conn, doi)` pour
      marquer la disparition au lieu d'insérer.
    Ces sentinelles sont comptées séparément (`not_found`) et exclues de
    `fetched`.

    Args:
        conn: `Connection` SA ouverte.
        adapter: instance source-spécifique async.
        log: logger.
        cross_import_dois_reader: callable `(conn, source) -> list[doi]`.
        marker_handler: optionnel ; si fourni, les sentinelles not-found y
            sont routées (`(conn, doi)`, charge de committer) au lieu de
            passer par `insert()`.
        dry_run: compte et log sans fetch ni insert.
        limit: nombre max de DOI à traiter.

    Returns:
        `PhaseMetrics` : `total` = DOI traités, `new` = inserts effectifs,
        `extras["fetched"]` = records reçus de l'API, `extras["not_found"]`
        = DOI confirmés absents (backoff enregistré).
    """
    adapter.configure(conn)

    dois = cross_import_dois_reader(conn, adapter.source_key)
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
    progress = {"processed": 0, "fetched": 0, "inserted": 0, "not_found": 0}

    async with httpx.AsyncClient() as client:
        request_delay = getattr(adapter, "request_delay_s", 0.0)

        async def process_batch(batch: list[str], batch_idx: int) -> None:
            # Breaker tripé (source à bout de budget / en panne) : on saute les
            # lots restants. Les lots en vol au moment du trip lèvent
            # `SourceUnavailableError` (avalée ci-dessous) ; les suivants no-op ici.
            if breaker is not None and breaker.tripped:
                return
            async with sem:
                try:
                    records = list(await adapter.fetch_async(client, batch))
                except Exception as e:
                    log.error("Erreur sur lot %d (%d DOI) : %s", batch_idx, len(batch), e)
                    records = []
                if request_delay:
                    await asyncio.sleep(request_delay)

            # Les sentinelles `not_found` ne sont pas des records API : on les
            # compte à part, mais on les `insert()` quand même (l'adapter les
            # route vers le backoff `doi_lookups` / le stub `staging`).
            real = [r for r in records if not is_not_found_marker(r)]
            progress["fetched"] += len(real)
            progress["not_found"] += len(records) - len(real)
            for record in records:
                try:
                    async with db_lock:
                        if marker_handler is not None and is_not_found_marker(record):
                            await asyncio.to_thread(marker_handler, conn, record["_doi"])
                        else:
                            inserted_one = await asyncio.to_thread(adapter.insert, conn, record)
                            if inserted_one:
                                progress["inserted"] += 1
                except Exception as e:
                    log.warning("Erreur insertion (%s) : %s", adapter.source_key, e)

            progress["processed"] += len(batch)
            if progress["processed"] % 100 == 0 or progress["processed"] >= total:
                duplicates = progress["fetched"] - progress["inserted"]
                log.info(
                    "  %s %d/%d — %d records (%d nouveaux, %d doublons, %d not-found)",
                    adapter.source_key,
                    progress["processed"],
                    total,
                    progress["fetched"],
                    progress["inserted"],
                    duplicates,
                    progress["not_found"],
                )

        await asyncio.gather(*(process_batch(b, i) for i, b in enumerate(batches)))

    if breaker is not None and breaker.tripped:
        log.warning(
            "Source %s à bout (429/5xx répétés) — %d/%d DOI traités, reste sauté"
            " (retry au prochain run)",
            adapter.source_key,
            progress["processed"],
            total,
        )

    duplicates = progress["fetched"] - progress["inserted"]
    log.info(
        "Terminé %s : %d DOI interrogés, %d records (%d nouveaux, %d doublons déjà en staging),"
        " %d not-found (backoff)",
        adapter.source_key,
        total,
        progress["fetched"],
        progress["inserted"],
        duplicates,
        progress["not_found"],
    )
    return PhaseMetrics(
        total=total,
        new=progress["inserted"],
        extras={"fetched": progress["fetched"], "not_found": progress["not_found"]},
    )
