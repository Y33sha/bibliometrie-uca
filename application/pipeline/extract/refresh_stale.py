"""Orchestrateur du refresh des rows staging stale d'une source.

Sélectionne les rows dont `last_seen_at` a dépassé `STALE_REFRESH_AFTER_DAYS` et les refetche **par leur identifiant natif** (`staging.source_id`) — pas par DOI. Toute row a un `source_id`, donc toute row est refetchable, avec ou sans DOI.

Trois issues par row (cf. `application.ports.pipeline.extract.refresh_stale`) :

- record trouvé → UPSERT (`raw_data` rafraîchi si le hash change, `last_seen_at` toujours bumpé) ;
- absence confirmée (réponse valide, zéro record) → `disappeared_at` ;
- échec transitoire (réseau, 429, réponse malformée) → no-op, retry au run suivant.

Le comportement spécifique à chaque source (endpoint, auth, requête/réponse) est délégué à un adapter `RefreshStaleAdapter`. Implémentation async via `run_fetch_pool` (pool de `max_concurrent` workers) avec circuit-breaker par source.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import partial

import httpx
from sqlalchemy import Connection

from application.pipeline._fetch_pool import run_fetch_pool
from application.pipeline.extract.base import scoped_logger
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.signals import filter_configured, select_targets, timed_metrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    FetchOutcome,
    RefreshStaleAdapter,
    StaleRow,
)
from domain.sources.registry import ALL_SOURCES

__all__ = ["refresh", "run_phase"]

COMMIT_EVERY = 50

# Dépendances techniques du phasage, injectées par le composition-root.
RefreshOne = Callable[[str, "list[int] | None"], PhaseMetrics]
"""Refetch stale d'une source (conn + adapter + breaker), bornée à `years`. Rend des métriques portant déjà l'éventuel signal `source_unavailable`."""
CredentialsMissing = Callable[[str], "str | None"]
"""`(source) -> motif d'absence de credentials | None si configurée`."""
GetYearsForWindow = Callable[["int | None"], "list[int] | None"]
"""`(start_year) -> années de la fenêtre du run | None (tout l'historique)`."""


def run_phase(
    *,
    sources: set[str] | None,
    include_wos: bool,
    year: int | None,
    start_year: int | None,
    refresh_one: RefreshOne,
    credentials_missing: CredentialsMissing,
    get_years_for_window: GetYearsForWindow,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Rafraîchit le stale de chaque source configurée, bornée à la fenêtre d'années du run.

    WoS est opt-in (`--include-wos`). Fenêtre d'années : `--year` cible une seule année, sinon `[start_year … courante]` ; `theses` ignore la borne large (tout l'historique des PPN), mais suit `--year`. Les sources non configurées sont sautées avec un signal `source_unconfigured`.
    """
    metrics = PhaseMetrics()
    targets = select_targets(ALL_SOURCES, sources, include_wos=include_wos)
    configured = filter_configured(
        targets,
        metrics,
        credentials_missing=credentials_missing,
        logger=logger,
        phase="refresh_stale",
    )

    years_default = [int(year)] if year else get_years_for_window(start_year)
    years_theses = [int(year)] if year else None

    by_source: dict[str, dict[str, float]] = {}
    for target in configured:
        row_years = years_theses if target == "theses" else years_default
        source_metrics, duration = timed_metrics(partial(refresh_one, target, row_years))
        metrics.merge(source_metrics)
        by_source[target] = {
            "interrogated": source_metrics.total,
            "refreshed": source_metrics.updated,
            "unchanged": source_metrics.unchanged,
            "disappeared": source_metrics.extras.get("disappeared", 0),
            "duration_s": round(duration, 1),
        }

    if by_source:
        metrics.details["table"] = {
            "rows": [{"key": source, **summary} for source, summary in by_source.items()]
        }
    return metrics


async def refresh(
    conn: Connection,
    adapter: RefreshStaleAdapter,
    log: logging.Logger,
    *,
    years: list[int] | None = None,
    breaker: CircuitBreaker | None = None,
) -> PhaseMetrics:
    """Refetche par id natif les rows stale de la source de l'adapter.

    `years` borne le refresh à la fenêtre d'années du run courant (via `source_publications.pub_year`) ; `None` = tout le stale de la source.

    `updated` = `raw_data` réécrit (hash changé) ; `unchanged` = re-vu identique (seul `last_seen_at` bumpé) ; `errors` = fetchs transitoires échoués ; `extras["disappeared"]` = absences confirmées marquées `disappeared_at`.
    """
    adapter.configure(conn)
    slog = scoped_logger(log, adapter.source_key)

    stale = adapter.find_stale(conn, years)
    total = len(stale)
    slog.info("%d rows stale", total)

    metrics = PhaseMetrics(seen=total)
    if total == 0:
        return metrics

    request_delay = getattr(adapter, "request_delay_s", 0.0)
    processed = 0

    async def _fetch(client: httpx.AsyncClient, row: StaleRow) -> FetchOutcome:
        try:
            outcome = await adapter.fetch_by_native_id(client, row.source_id)
        except Exception as e:
            # Breaker tripé pendant le fetch : abandon silencieux, le log unique vient après le pool.
            if not (breaker is not None and breaker.tripped):
                slog.error("erreur sur %s : %s", row.source_id, e)
            outcome = None
        if request_delay:
            await asyncio.sleep(request_delay)
        return outcome

    def _write(conn: Connection, row: StaleRow, outcome: FetchOutcome) -> None:
        nonlocal processed
        if outcome is None:
            metrics.add(errors=1)
        elif outcome is NOT_FOUND:
            adapter.mark_disappeared(conn, row.source_id)
            metrics.add(disappeared=1)
        else:
            assert isinstance(outcome, FetchedRecord)
            changed = adapter.save_refreshed(conn, row.source_id, outcome)
            metrics.add(updated=1) if changed else metrics.add(unchanged=1)
        processed += 1

    await run_fetch_pool(
        stale,
        conn,
        max_concurrent=adapter.max_concurrent,
        commit_every=COMMIT_EVERY,
        fetch=_fetch,
        write=_write,
        should_continue=lambda: breaker is None or not breaker.tripped,
    )

    if breaker is not None and breaker.tripped:
        slog.warning(
            "indisponible (429/5xx répétés) — abandon, %d/%d rows traitées, reste au prochain run",
            processed,
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
