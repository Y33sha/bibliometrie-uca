"""Orchestrateur du refresh des rows staging stale d'une source.

Sélectionne les rows dont `last_seen_at` a dépassé `STALE_REFRESH_AFTER_DAYS`
et les refetche **par leur identifiant natif** (`staging.source_id`) — pas par
DOI. Toute row a un `source_id`, donc toute row est refetchable, avec ou sans DOI.

Trois issues par row (cf. `application.ports.pipeline.extract.refresh_stale`) :

- record trouvé → UPSERT (`raw_data` rafraîchi si le hash change, `last_seen_at`
  toujours bumpé) ;
- absence confirmée (réponse valide, zéro record) → `disappeared_at` ;
- échec transitoire (réseau, 429, réponse malformée) → no-op, retry au run suivant.

Le comportement spécifique à chaque source (endpoint, auth, requête/réponse) est
délégué à un adapter `RefreshStaleAdapter`. Implémentation async (`httpx.AsyncClient`
+ pool de `max_concurrent` workers) avec circuit-breaker par source, sur le modèle
de `application.pipeline.extract.fetch_missing_doi.run_async`.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import Connection

from application.pipeline.extract.base import scoped_logger
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    RefreshStaleAdapter,
)

__all__ = ["refresh"]

COMMIT_EVERY = 50


async def refresh(
    conn: Connection,
    adapter: RefreshStaleAdapter,
    log: logging.Logger,
    *,
    years: list[int] | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Refetche par id natif les rows stale de la source de l'adapter.

    `years` borne le refresh à la fenêtre d'années du run courant (via
    `source_publications.pub_year`) ; `None` = tout le stale de la source.

    Ne ferme pas la connexion (responsabilité du caller). `updated` = `raw_data`
    réécrit (hash changé) ; `unchanged` = re-vu identique (seul `last_seen_at`
    bumpé) ; `errors` = fetchs transitoires échoués ; `extras["disappeared"]` =
    absences confirmées marquées `disappeared_at`.
    """
    adapter.configure(conn)
    slog = scoped_logger(log, adapter.source_key)

    stale = adapter.find_stale(conn, years)
    if limit:
        stale = stale[:limit]
    total = len(stale)
    slog.info("%d rows stale", total)

    if dry_run or total == 0:
        return PhaseMetrics(seen=total)

    # Sérialise les writes : la `Connection` SA sync n'est pas thread-safe, or
    # `asyncio.to_thread` exécute dans un ThreadPoolExecutor partagé.
    db_lock = asyncio.Lock()
    progress = {"processed": 0}
    metrics = PhaseMetrics(seen=total)

    # Pool de `max_concurrent` workers tirant les rows d'un itérateur partagé
    # (cf. `fetch_missing_doi.run_async`). `next()` est atomique en asyncio
    # mono-thread ; le breaker se vérifie avant chaque tirage → dès qu'il trip,
    # chaque worker finit sa row en vol puis s'arrête.
    row_iter = iter(stale)

    async with httpx.AsyncClient() as client:
        request_delay = getattr(adapter, "request_delay_s", 0.0)

        async def worker() -> None:
            for row in row_iter:
                if breaker is not None and breaker.tripped:
                    return
                try:
                    outcome = await adapter.fetch_by_native_id(client, row.source_id)
                except Exception as e:
                    if breaker is not None and breaker.tripped:
                        return
                    slog.error("erreur sur %s : %s", row.source_id, e)
                    outcome = None
                if request_delay:
                    await asyncio.sleep(request_delay)

                async with db_lock:
                    if outcome is None:
                        metrics.add(errors=1)
                    elif outcome is NOT_FOUND:
                        await asyncio.to_thread(adapter.mark_disappeared, conn, row.source_id)
                        metrics.add(disappeared=1)
                    else:
                        assert isinstance(outcome, FetchedRecord)
                        changed = await asyncio.to_thread(
                            adapter.save_refreshed, conn, row.source_id, outcome
                        )
                        metrics.add(updated=1) if changed else metrics.add(unchanged=1)

                    progress["processed"] += 1
                    if progress["processed"] % COMMIT_EVERY == 0:
                        await asyncio.to_thread(conn.commit)

        await asyncio.gather(*(worker() for _ in range(adapter.max_concurrent)))

    conn.commit()

    if breaker is not None and breaker.tripped:
        slog.warning(
            "indisponible (429/5xx répétés) — abandon, %d/%d rows traitées, reste au prochain run",
            progress["processed"],
            total,
        )
    slog.info(
        "terminé : %d interrogées, %d rafraîchies, %d inchangées, %d disparues, %d erreurs",
        total,
        metrics.updated,
        metrics.unchanged,
        metrics.extras.get("disappeared", 0),
        metrics.errors,
    )
    return metrics
