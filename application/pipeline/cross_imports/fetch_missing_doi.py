"""Orchestrateur du fetch des DOI manquants dans une source cible.

Pour chaque DOI présent dans d'autres sources mais absent de la cible, interroge l'API de la cible et insère le record dans staging.

Le comportement spécifique à chaque source (endpoint, auth, format de requête/réponse, SQL d'insertion) est délégué à un adapter qui implémente `AsyncFetchMissingDoiAdapter` (`application/ports/pipeline/cross_imports/fetch_missing_doi.py`).

Implémentation async (`httpx.AsyncClient` + pool de `max_concurrent` workers par source) pour saturer les rate-limits autorisés.

Utilisé par la phase `cross_imports` du pipeline, une fois par source cible (hal, openalex, wos, scanr, crossref).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import httpx
from sqlalchemy import Connection

from application.pipeline.logging_scope import scoped_logger
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.pipeline.cross_imports.fetch_missing_doi import (
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
    limit: int | None = None,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Boucle principale : DOIs → fetch async → insert.

    Lance les fetchs HTTP en parallèle via `asyncio.gather`, bornés par un sémaphore `adapter.max_concurrent` pour respecter le rate-limit de l'API. Les inserts DB restent sync, délégués au threadpool via `asyncio.to_thread` et sérialisés par un `asyncio.Lock` (la `Connection` SA sync n'est pas thread-safe).

    Un DOI confirmé absent par la source (réponse vide / 404) revient sous forme de sentinelle `not_found_marker`. Routage de la sentinelle :
    - sans `marker_handler` (cross-import) : `insert()` la route vers le backoff (`doi_lookups` / stub `staging` Crossref) ;
    - avec `marker_handler` (refresh stale) : appelé `(conn, doi)` pour marquer la disparition au lieu d'insérer.
    Ces sentinelles sont comptées séparément (`not_found`) et exclues de `fetched`.

    Args:
        conn: `Connection` SA ouverte.
        adapter: instance source-spécifique async.
        log: logger.
        cross_import_dois_reader: callable `(conn, source) -> list[doi]`.
        marker_handler: optionnel ; si fourni, les sentinelles not-found y sont routées (`(conn, doi)`, charge de committer) au lieu de passer par `insert()`.
        limit: nombre max de DOI à traiter.

    Returns:
        `PhaseMetrics` : `total` = DOI traités, `new` = inserts effectifs, `extras["fetched"]` = records reçus de l'API, `extras["not_found"]` = DOI confirmés absents (backoff enregistré).
    """
    adapter.configure(conn)
    slog = scoped_logger(log, adapter.source_key)

    dois = cross_import_dois_reader(conn, adapter.source_key)
    slog.info("%d DOI manquants", len(dois))

    if limit:
        dois = dois[:limit]
        slog.info("limité à %d DOI", len(dois))

    total = len(dois)
    if total == 0:
        return PhaseMetrics()

    batches = [dois[i : i + adapter.batch_size] for i in range(0, total, adapter.batch_size)]

    # Sérialise les inserts : la `Connection` SA sync n'est pas thread-safe, or `asyncio.to_thread` exécute dans un ThreadPoolExecutor partagé.
    db_lock = asyncio.Lock()
    progress = {"processed": 0, "fetched": 0, "inserted": 0, "not_found": 0}

    # Pool de `max_concurrent` workers tirant les lots d'un itérateur partagé,
    # plutôt qu'un fan-out de toutes les coroutines d'un coup. `next()` est
    # atomique en asyncio mono-thread (aucun `await` entre deux tirages) : pas de
    # lot dupliqué ni sauté. Le breaker se vérifie *avant chaque tirage* → dès
    # qu'il trip, chaque worker finit son lot en vol puis s'arrête sans tirer les
    # suivants. C'est le « on sort de la boucle » d'un vrai circuit-breaker : pas
    # de log d'erreur par lot restant, un seul log d'abandon après le gather.
    batch_iter = iter(enumerate(batches))

    async with httpx.AsyncClient() as client:
        request_delay = getattr(adapter, "request_delay_s", 0.0)

        async def worker() -> None:
            for batch_idx, batch in batch_iter:
                if breaker is not None and breaker.tripped:
                    return
                try:
                    records = list(await adapter.fetch_async(client, batch))
                except Exception as e:
                    # Breaker tripé pendant le fetch (source indisponible) : abandon silencieux, le log unique vient après le gather.
                    if breaker is not None and breaker.tripped:
                        return
                    slog.error("erreur sur lot %d (%d DOI) : %s", batch_idx, len(batch), e)
                    records = []
                if request_delay:
                    await asyncio.sleep(request_delay)

                # Les sentinelles `not_found` ne sont pas des records API : on les compte à part, mais on les `insert()` quand même (l'adapter les route vers le backoff `doi_lookups` / le stub `staging`).
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
                        slog.warning("erreur insertion : %s", e)

                progress["processed"] += len(batch)
                if progress["processed"] % 100 == 0 or progress["processed"] >= total:
                    duplicates = progress["fetched"] - progress["inserted"]
                    slog.info(
                        "%d/%d — %d records (%d nouveaux, %d doublons, %d not-found)",
                        progress["processed"],
                        total,
                        progress["fetched"],
                        progress["inserted"],
                        duplicates,
                        progress["not_found"],
                    )

        await asyncio.gather(*(worker() for _ in range(adapter.max_concurrent)))

    if breaker is not None and breaker.tripped:
        slog.warning(
            "indisponible (429/5xx répétés) — abandon, %d/%d DOI traités, reste au prochain run",
            progress["processed"],
            total,
        )

    duplicates = progress["fetched"] - progress["inserted"]
    slog.info(
        "terminé : %d DOI interrogés, %d records (%d nouveaux, %d doublons déjà en staging),"
        " %d not-found (backoff)",
        total,
        progress["fetched"],
        progress["inserted"],
        duplicates,
        progress["not_found"],
    )
    return PhaseMetrics(
        seen=total,
        new=progress["inserted"],
        extras={"fetched": progress["fetched"], "not_found": progress["not_found"]},
    )
