"""Orchestrateur du fetch des DOI manquants dans une source cible.

Pour chaque DOI présent dans d'autres sources mais absent de la cible, interroge l'API de la cible et insère le record dans `staging`.

Le comportement spécifique à chaque source (endpoint, auth, format de requête/réponse, SQL d'insertion) est délégué à un adapter qui implémente `AsyncFetchMissingDoiAdapter` (`application/ports/pipeline/cross_imports/fetch_missing_doi.py`).

Implémentation async via `run_fetch_pool` (pool de `max_concurrent` workers par source) pour saturer les rate-limits autorisés.

Utilisé par la phase `cross_imports` du pipeline, une fois par source cible.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import Connection

from application.pipeline._fetch_pool import run_fetch_pool
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
    limit: int | None = None,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Boucle principale : DOIs → fetch async → insert.

    Les fetchs HTTP tournent concurremment via `run_fetch_pool` (pool de `adapter.max_concurrent` workers), ce qui borne le débit au rate-limit de l'API. Les inserts DB restent sync, sérialisés par le pool sous un lock (la `Connection` SA sync n'est pas thread-safe) ; chaque lot est committé en une transaction (l'adapter source ne commite pas).

    Quand la source confirme l'absence d'un DOI (réponse vide / 404), `fetch_async` renvoie une sentinelle `not_found_marker` au lieu d'un record : comptée à part (`not_found`, exclue de `fetched`) et passée à `adapter.insert()`, qui la mémorise dans `doi_lookups`.

    Args:
        conn: `Connection` SA ouverte.
        adapter: instance source-spécifique async.
        log: logger.
        cross_import_dois_reader: callable `(conn, source) -> list[doi]`.
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

    progress = {"processed": 0, "fetched": 0, "inserted": 0, "not_found": 0}
    request_delay = getattr(adapter, "request_delay_s", 0.0)
    items = list(enumerate(batches))

    async def _fetch(
        client: httpx.AsyncClient, item: tuple[int, list[str]]
    ) -> list[dict[str, Any]]:
        batch_idx, batch = item
        try:
            records = list(await adapter.fetch_async(client, batch))
        except Exception as e:
            # Breaker tripé pendant le fetch (source indisponible) : abandon silencieux, le log unique vient après le pool.
            if not (breaker is not None and breaker.tripped):
                slog.error("erreur sur lot %d (%d DOI) : %s", batch_idx, len(batch), e)
            records = []
        if request_delay:
            await asyncio.sleep(request_delay)
        return records

    def _write(
        conn: Connection, item: tuple[int, list[str]], records: list[dict[str, Any]]
    ) -> None:
        batch_idx, batch = item
        real = [r for r in records if not is_not_found_marker(r)]
        progress["fetched"] += len(real)
        progress["not_found"] += len(records) - len(real)

        # Un lot = une transaction (le pool commite après ce write). Sur erreur,
        # rollback (désempoisonne la connexion), le lot repartira au prochain run.
        try:
            batch_inserted = 0
            for record in records:
                if adapter.insert(conn, record):
                    batch_inserted += 1
            progress["inserted"] += batch_inserted
        except Exception as e:
            conn.rollback()
            slog.warning(
                "lot %d (%d DOI) : insertion échouée, rollback — %s", batch_idx, len(batch), e
            )

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
