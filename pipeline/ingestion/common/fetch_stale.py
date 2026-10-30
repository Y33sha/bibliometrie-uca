"""Phase `fetch_stale` : nouvelle lecture des documents de `staging` que le moissonnage n'a pas revus depuis `fetch_stale_after_days` jours. Une tâche par source, en parallèle.

Chaque document est relu par son identifiant natif. Trois issues :

- document trouvé → écriture dans `staging` ;
- absence confirmée (réponse valide, aucun document) → document marqué disparu (`disappeared_at`) ;
- source indisponible (réseau, 429, réponse illisible) → nouvelle tentative au run suivant.

Le délai étale la charge : chaque passe reprend seulement les documents qui viennent de le franchir.

La relecture se borne aux années que le run moissonne ; une thèse en cours est relue quelle que soit la fenêtre. Un mode dont la policy exclut la phase la saute (`daily`). WoS est opt-in (`--include-wos`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from domain.config import ConfigKey
from domain.sources.registry import ALL_SOURCES, Source, source_label
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.stale_refetch import refresh
from pipeline.runtime.config import delay, window_years
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import select_targets, skipped
from pipeline.task_runner import TaskRun, TaskStep, run_tasks

RefreshOne = Callable[[PhaseContext, str, "list[int] | None"], PhaseMetrics]
"""Nouvelle lecture des documents d'une source, bornée aux années données."""
GetYearsForWindow = Callable[[PhaseContext, "int | None", "int | None"], "list[int] | None"]
"""Années de la fenêtre du run, ou `None` pour tout l'historique."""


@dataclass(frozen=True)
class FetchStalePhase:
    refresh_one: RefreshOne
    get_years_for_window: GetYearsForWindow

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Relit en parallèle les documents anciens de chaque source retenue, et assemble les métriques."""
        options, logger = ctx.options, ctx.logger
        metrics = PhaseMetrics()
        if not options.policy.fetch_stale:
            logger.info("%sSautée en mode %s", LAST_BRANCH, options.mode)
            return metrics
        targets = set(select_targets(ALL_SOURCES, options.sources, include_wos=options.include_wos))

        years = self.get_years_for_window(ctx, options.start_year, options.year)

        def task(source: str) -> TaskRun:
            return lambda ctx: self.refresh_one(ctx, source, years)

        def selected(source: str) -> Callable[[PhaseContext], bool]:
            return lambda _ctx: source in targets

        by_task = run_tasks(
            "fetch_stale",
            {
                f"fetch_stale.{source}": TaskStep(
                    task(source),
                    label=source_label(source),
                    progress_bar=True,
                    when=selected(source),
                )
                for source in ALL_SOURCES
            },
            ctx,
        )

        by_source: dict[str, dict[str, float | None]] = {}
        for source in ALL_SOURCES:
            source_metrics = by_task[f"fetch_stale.{source}"]
            metrics.merge(source_metrics)
            if source not in targets or skipped(source_metrics):
                continue
            by_source[source] = {
                "interrogated": source_metrics.total,
                "refreshed": source_metrics.updated,
                "unchanged": source_metrics.unchanged,
                "disappeared": source_metrics.extras.get("disappeared", 0),
                "duration_s": source_metrics.duration_s,
            }

        if by_source:
            metrics.details["table"] = {
                "rows": [{"key": source, **summary} for source, summary in by_source.items()]
            }
        return metrics


def build() -> Phase:
    return FetchStalePhase(
        refresh_one=_run_fetch_stale,
        get_years_for_window=_get_years_for_window,
    )


def _get_years_for_window(
    ctx: PhaseContext, start_year: int | None, year: int | None
) -> list[int] | None:
    """Années de la fenêtre du run (`window_years`)."""
    with ctx.open_tx() as conn:
        return window_years(conn, start_year=start_year, year=year)


def _run_fetch_stale(ctx: PhaseContext, target: str, years: list[int] | None) -> PhaseMetrics:
    """Nouvelle lecture des documents anciens d'une source, sur sa propre connexion."""
    refetch = ADAPTERS[Source(target)].stale_refetch()
    with ctx.open_tx() as conn:
        after_days = delay(conn, ConfigKey.FETCH_STALE_AFTER_DAYS)
        return asyncio.run(refresh(conn, refetch, ctx.logger, after_days=after_days, years=years))
