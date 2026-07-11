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
de `application.pipeline.cross_imports.fetch_missing_doi.run_async`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import partial

import httpx
from sqlalchemy import Connection

from application.pipeline.extract.base import scoped_logger
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.signals import filter_configured, timed_metrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    RefreshStaleAdapter,
)
from domain.sources.registry import ALL_SOURCES

__all__ = ["refresh", "run_phase"]

COMMIT_EVERY = 50

# Dépendances techniques du phasage, injectées par le composition-root.
RefreshOne = Callable[[str, "list[int] | None"], PhaseMetrics]
"""Refetch stale d'une source (conn + adapter + breaker), bornée à `years`. Rend des métriques
portant déjà l'éventuel signal `source_unavailable`."""
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

    WoS est opt-in (`--include-wos`). Fenêtre d'années : `--year` cible une seule année, sinon
    `[start_year … courante]` ; `theses` ignore la borne large (tout l'historique des PPN), mais
    suit `--year`. Les sources non configurées sont sautées avec un signal `source_unconfigured`.
    """
    metrics = PhaseMetrics()
    allowed = set(ALL_SOURCES) - ({"wos"} if not include_wos else set())
    effective = (set(sources) if sources else allowed) & allowed
    targets = [t for t in ALL_SOURCES if t in effective]
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
