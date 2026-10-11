"""Orchestrateur du fetch des DOI manquants dans une source cible.

Pour chaque DOI présent dans d'autres sources mais absent de la cible, interroge l'API de la cible et insère le record dans `staging`.

Le comportement spécifique à chaque source (endpoint, auth, format de requête/réponse, SQL d'insertion) est délégué à un adapter qui implémente `AsyncFetchMissingDoiAdapter` (`application/ports/pipeline/fetch_missing/doi.py`).

Implémentation async via `run_fetch_pool` (pool de `max_concurrent` workers par source) pour saturer les rate-limits autorisés.

Utilisé par la phase `fetch_missing` du pipeline, une fois par source cible.
"""

from __future__ import annotations

import asyncio
import logging

import httpx2
from sqlalchemy import Connection

from application.pipeline._fetch_pool import run_fetch_pool
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.pipeline.fetch_missing.doi import (
    AsyncFetchMissingDoiAdapter,
    DoiBatchResult,
    FailedDoiRecorder,
    MissingDoisReader,
)
from pipeline.libelles import branche_de_source
from pipeline.logging_scope import scoped_logger
from pipeline.metrics import PhaseMetrics
from pipeline.progression import progression

__all__ = ["AsyncFetchMissingDoiAdapter", "MissingDoisReader", "run_async"]


async def run_async(
    conn: Connection,
    adapter: AsyncFetchMissingDoiAdapter,
    log: logging.Logger,
    *,
    missing_dois_reader: MissingDoisReader,
    record_not_found: FailedDoiRecorder,
    retry_after_days: int,
    limit: int | None = None,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Boucle principale : DOIs → fetch async → insert.

    Les fetchs HTTP tournent concurremment via `run_fetch_pool` (pool de `adapter.max_concurrent` workers), ce qui borne le débit au rate-limit de l'API. Les inserts DB restent sync, sérialisés par le pool sous un lock (la `Connection` SA sync n'est pas thread-safe) ; chaque lot est committé en une transaction (l'adapter source ne commite pas).

    `fetch_async` rend les notices trouvées et les DOI dont la source a confirmé l'absence. `record_not_found` inscrit ces derniers dans `failed_lookups`. Un DOI ni trouvé ni absent attend le run suivant.

    Args:
        conn: `Connection` SA ouverte.
        adapter: instance source-spécifique async.
        log: logger.
        missing_dois_reader: callable `(conn, source) -> list[doi]`.
        record_not_found: callable `(conn, source, doi, retry_after_days)`.
        retry_after_days: délai, en jours, avant de chercher de nouveau un DOI confirmé absent.
        limit: nombre max de DOI à traiter.

    Returns:
        `PhaseMetrics` : `total` = DOI traités, `new` = inserts effectifs, `extras["fetched"]` = records reçus de l'API, `extras["not_found"]` = DOI confirmés absents (backoff enregistré).
    """
    adapter.configure(conn)
    slog = scoped_logger(log, adapter.source_key)

    dois = missing_dois_reader(conn, adapter.source_key)

    if limit and len(dois) > limit:
        slog.info(
            "plafond de %d DOI par exécution, %d reportés aux suivantes", limit, len(dois) - limit
        )
        dois = dois[:limit]

    total = len(dois)
    if total == 0:
        return PhaseMetrics()

    batches = [dois[i : i + adapter.batch_size] for i in range(0, total, adapter.batch_size)]

    progress = {"processed": 0, "fetched": 0, "inserted": 0, "not_found": 0}
    request_delay = getattr(adapter, "request_delay_s", 0.0)
    items = list(enumerate(batches))

    async def _fetch(client: httpx2.AsyncClient, item: tuple[int, list[str]]) -> DoiBatchResult:
        batch_idx, batch = item
        try:
            result = await adapter.fetch_async(client, batch)
        except Exception as e:
            slog.error("erreur sur lot %d (%d DOI) : %s", batch_idx, len(batch), e)
            result = DoiBatchResult()
        if request_delay:
            await asyncio.sleep(request_delay)
        return result

    with progression(
        total, branche_de_source(adapter.source_key), slog, compte_retenus=True
    ) as avancement:

        def _write(conn: Connection, item: tuple[int, list[str]], result: DoiBatchResult) -> None:
            batch_idx, batch = item
            progress["fetched"] += len(result.records)
            progress["not_found"] += len(result.not_found)

            # Un lot = une transaction (le pool commite après ce write). Sur erreur,
            # rollback (désempoisonne la connexion), le lot repartira au prochain run.
            batch_inserted = 0
            try:
                for record in result.records:
                    if adapter.insert(conn, record):
                        batch_inserted += 1
                for doi in result.not_found:
                    record_not_found(conn, adapter.source_key, doi, retry_after_days)
                progress["inserted"] += batch_inserted
            except Exception as e:
                conn.rollback()
                slog.warning(
                    "lot %d (%d DOI) : insertion échouée, rollback — %s", batch_idx, len(batch), e
                )

            progress["processed"] += len(batch)
            avancement.avance(len(batch))
            avancement.retient(batch_inserted)

        await run_fetch_pool(
            items,
            conn,
            max_concurrent=adapter.max_concurrent,
            commit_every=1,
            fetch=_fetch,
            write=_write,
            should_continue=lambda: breaker is None or not breaker.tripped,
        )

    if breaker is not None and breaker.tripped:
        slog.warning(
            "indisponible (429/5xx répétés) — abandon, %d/%d DOI traités, reste au prochain run",
            progress["processed"],
            total,
        )

    return PhaseMetrics(
        seen=total,
        new=progress["inserted"],
        extras={"fetched": progress["fetched"], "not_found": progress["not_found"]},
    )
