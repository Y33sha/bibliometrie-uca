"""Phase `fetch_stale` : nouvelle lecture des documents de `staging` que le moissonnage n'a pas revus depuis `fetch_stale_after_days` jours. Tâches `fetch_stale.<source>`.

Chaque document est relu **par son identifiant natif** (`staging.source_id`), avec ou sans DOI. Trois issues :

- document trouvé → écriture dans `staging` (`raw_data` réécrit si l'empreinte change, `last_seen_at` toujours mis à jour) ;
- absence confirmée (réponse valide, zéro document) → `disappeared_at` ;
- source indisponible (réseau, 429, réponse illisible) → rien, nouvelle tentative au run suivant.

Le délai étale la charge sans `LIMIT` : chaque passe ramasse seulement les documents qui viennent de le franchir.

Le mode `daily` saute la phase. La fenêtre d'années du run (`start_year`, `year`) borne la relecture aux années que le run moissonne. `theses` relit tout son historique, sauf sous `--year`. WoS est opt-in (`--include-wos`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from domain.config import ConfigKey
from domain.sources.registry import ALL_SOURCES, source_label
from pipeline.ingestion.common.stale_refetch import (
    StaleRefetch,
    refresh,
)
from pipeline.ingestion.crossref.fetch_stale import CrossrefStaleRefetch
from pipeline.ingestion.datacite.fetch_stale import DataciteStaleRefetch
from pipeline.ingestion.hal.fetch_stale import HalStaleRefetch
from pipeline.ingestion.openalex.fetch_stale import OpenalexStaleRefetch
from pipeline.ingestion.scanr.fetch_stale import ScanrStaleRefetch
from pipeline.ingestion.theses.fetch_stale import ThesesStaleRefetch
from pipeline.ingestion.wos.fetch_stale import WosStaleRefetch
from pipeline.runtime.config import delay, get_years
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import select_targets, skipped
from pipeline.task_runner import TaskRun, TaskStep, run_tasks

# Dépendances techniques du phasage, injectées par le composition-root.
RefreshOne = Callable[[PhaseContext, str, "list[int] | None"], PhaseMetrics]
"""Nouvelle lecture des documents d'une source, bornée à `years`."""
GetYearsForWindow = Callable[[PhaseContext, "int | None"], "list[int] | None"]
"""`(ctx, start_year) -> années de la fenêtre du run | None (tout l'historique)`."""


@dataclass(frozen=True)
class FetchStalePhase:
    refresh_one: RefreshOne
    get_years_for_window: GetYearsForWindow

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Relit les documents anciens de chaque source, dans la fenêtre d'années du run.

        La phase est sautée dans un mode dont la policy exclut `fetch_stale`. WoS est opt-in (`--include-wos`). Fenêtre d'années : `--year` cible une seule année, sinon `[start_year … courante]` ; `theses` ignore la borne large (tout l'historique des PPN), mais suit `--year`.
        """
        options, logger = ctx.options, ctx.logger
        metrics = PhaseMetrics()
        if not options.policy.fetch_stale:
            logger.info("%sSautée en mode %s", LAST_BRANCH, options.mode)
            return metrics
        targets = set(select_targets(ALL_SOURCES, options.sources, include_wos=options.include_wos))

        year = options.year
        years_default = [int(year)] if year else self.get_years_for_window(ctx, options.start_year)
        years_theses = [int(year)] if year else None

        def task(source: str) -> TaskRun:
            row_years = years_theses if source == "theses" else years_default
            return lambda ctx: self.refresh_one(ctx, source, row_years)

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


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return FetchStalePhase(
        refresh_one=_run_fetch_stale,
        get_years_for_window=_get_years_for_window,
    )


def _get_years_for_window(ctx: PhaseContext, start_year: int | None) -> list[int] | None:
    """Années de la fenêtre du run, de `start_year` à l'année courante."""
    with ctx.open_tx() as conn:
        return get_years(conn, start_year)


def _make_refetch(source: str) -> StaleRefetch:
    """Construit la nouvelle lecture par identifiant natif d'une source."""

    refetches: dict[str, type[StaleRefetch]] = {
        "hal": HalStaleRefetch,
        "openalex": OpenalexStaleRefetch,
        "wos": WosStaleRefetch,
        "scanr": ScanrStaleRefetch,
        "theses": ThesesStaleRefetch,
        "crossref": CrossrefStaleRefetch,
        "datacite": DataciteStaleRefetch,
    }
    return refetches[source]()


def _run_fetch_stale(ctx: PhaseContext, target: str, years: list[int] | None) -> PhaseMetrics:
    """Refetch par id natif des rows stale d'une source : trouvé → bump, absence → disappeared.

    `years` borne le refresh à la fenêtre d'années du run (None = tout le stale).
    """
    refetch = _make_refetch(target)
    with ctx.open_tx() as conn:
        after_days = delay(conn, ConfigKey.FETCH_STALE_AFTER_DAYS)
        return asyncio.run(refresh(conn, refetch, ctx.logger, after_days=after_days, years=years))
