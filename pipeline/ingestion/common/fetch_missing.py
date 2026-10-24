"""Phase `fetch_missing` : rattrapage des documents repérés dans une source mais absents d'une autre. Trois mécanismes, dans cet ordre :

1. **Recherche dans HAL par hal-id** (`pipeline.ingestion.hal.fetch_missing`) : hal-id repérés dans OpenAlex et ScanR.
2. **Recherche par NNT** : dans HAL, les thèses de theses.fr sans document HAL (`pipeline.ingestion.hal.fetch_missing`) ; dans theses.fr, les NNT repérés dans une autre source (`pipeline.ingestion.theses.fetch_missing`). Les deux tâches forment un groupe parallèle.
3. **Recherche par DOI** : pour chaque source cible, les DOI vus ailleurs et absents de la cible. Les tâches `fetch_missing.doi.<source>` forment un groupe parallèle.

Une recherche sans identifiant à chercher n'écrit rien. Une section dont aucune recherche n'a rien cherché se ferme sur « Rien à faire » (`silent_when_empty`).

Un identifiant cherché en vain est inscrit dans `failed_lookups` (`pipeline.ingestion.common.failed_lookups`). Il est cherché de nouveau après le délai `fetch_missing_retry_after_days`, sauf s'il est absent de son registre. WoS est opt-in (`--include-wos`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from domain.config import ConfigKey
from domain.sources.registry import DOI_SEARCHABLE_SOURCES, Source
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.doi_search import fetch_missing_doi
from pipeline.runtime.config import cap, delay, window_years
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import select_targets, skipped
from pipeline.runtime.parallel import RunParallel, run_parallel
from pipeline.task_runner import TaskRun, TaskStep, run_tasks

FetchChannel = Callable[[PhaseContext], PhaseMetrics]
"""Recherche HAL par hal-id ou par NNT : rend les métriques du canal."""
FetchDoiOne = Callable[[PhaseContext, str], PhaseMetrics]
"""Recherche par DOI dans une source cible."""

_HAL_BY_ID = "fetch_missing.hal_by_id"
_HAL_BY_NNT = "fetch_missing.hal_by_nnt"
_THESES_BY_NNT = "fetch_missing.theses_by_nnt"
_NNT_SECTION = "Recherche par NNT des thèses manquantes dans chaque source"


def _doi_task(target: str) -> str:
    return f"fetch_missing.doi.{target}"


def _summary(metrics: PhaseMetrics) -> dict[str, float | None]:
    """Ligne « par canal » de la table d'observabilité de la phase."""
    return {
        "interrogated": metrics.total,
        "new": metrics.new,
        "not_found": metrics.extras.get("not_found", 0),
        "duration_s": metrics.duration_s,
    }


@dataclass(frozen=True)
class FetchMissingPhase:
    fetch_hal_by_id: FetchChannel
    fetch_hal_by_nnt: FetchChannel
    fetch_theses_by_nnt: FetchChannel
    fetch_doi_one: FetchDoiOne
    run_parallel: RunParallel

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les canaux HAL puis le lot parallèle de la recherche par DOI, et assemble les métriques."""
        options = ctx.options
        hal = "hal" in options.sources
        theses = "theses" in options.sources
        # WoS opt-in.
        doi_targets = set(
            select_targets(DOI_SEARCHABLE_SOURCES, options.sources, include_wos=options.include_wos)
        )
        selected_tasks = {
            _HAL_BY_ID: hal,
            _HAL_BY_NNT: hal and options.mode == "full",
            _THESES_BY_NNT: theses,
            **{_doi_task(target): target in doi_targets for target in DOI_SEARCHABLE_SOURCES},
        }

        def when_selected(task: str) -> Callable[[PhaseContext], bool]:
            return lambda _ctx: selected_tasks[task]

        def doi(target: str) -> TaskRun:
            return lambda ctx: self.fetch_doi_one(ctx, target)

        by_task = run_tasks(
            "fetch_missing",
            {
                _HAL_BY_ID: TaskStep(
                    self.fetch_hal_by_id,
                    section="Recherche dans HAL des documents avec hal-id trouvés ailleurs",
                    when=when_selected(_HAL_BY_ID),
                    silent_when_empty=True,
                ),
                _HAL_BY_NNT: TaskStep(
                    self.fetch_hal_by_nnt,
                    section=_NNT_SECTION,
                    when=when_selected(_HAL_BY_NNT),
                    silent_when_empty=True,
                ),
                _THESES_BY_NNT: TaskStep(
                    self.fetch_theses_by_nnt,
                    section=_NNT_SECTION,
                    when=when_selected(_THESES_BY_NNT),
                    silent_when_empty=True,
                ),
                **{
                    _doi_task(target): TaskStep(
                        doi(target),
                        section="Recherche par DOI des documents manquants dans chaque source",
                        when=when_selected(_doi_task(target)),
                        silent_when_empty=True,
                    )
                    for target in DOI_SEARCHABLE_SOURCES
                },
            },
            ctx,
            parallel=self.run_parallel,
        )

        metrics = PhaseMetrics()
        by_channel: dict[str, dict[str, float | None]] = {}
        channels = {
            _HAL_BY_ID: "hal-id",
            _HAL_BY_NNT: "NNT",
            _THESES_BY_NNT: "NNT theses.fr",
            **{_doi_task(target): target for target in DOI_SEARCHABLE_SOURCES},
        }
        for task, key in channels.items():
            metrics.merge(by_task[task])
            if selected_tasks[task] and not skipped(by_task[task]):
                by_channel[key] = _summary(by_task[task])
        if by_channel:
            metrics.details["table"] = {
                "rows": [{"key": channel, **summary} for channel, summary in by_channel.items()]
            }
        return metrics


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return FetchMissingPhase(
        fetch_hal_by_id=_run_fetch_missing_hal_by_id,
        fetch_hal_by_nnt=_run_fetch_missing_hal_by_nnt,
        fetch_theses_by_nnt=_run_fetch_missing_theses_by_nnt,
        fetch_doi_one=_run_fetch_missing_doi,
        run_parallel=run_parallel,
    )


def _run_fetch_missing_hal_by_id(ctx: PhaseContext) -> PhaseMetrics:
    """Recherche dans HAL par hal-id (OpenAlex/ScanR) : documents absents du staging."""
    from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_id

    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        return asyncio.run(
            fetch_missing_hal_by_id(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _run_fetch_missing_hal_by_nnt(ctx: PhaseContext) -> PhaseMetrics:
    """Recherche dans HAL par NNT (theses.fr) : thèses soutenues sans document HAL."""
    from pipeline.ingestion.hal.fetch_missing import fetch_missing_hal_by_nnt

    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        return asyncio.run(
            fetch_missing_hal_by_nnt(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _run_fetch_missing_theses_by_nnt(ctx: PhaseContext) -> PhaseMetrics:
    """Recherche dans theses.fr par NNT : thèses trouvées dans d'autres sources, absentes du staging theses.fr."""
    from pipeline.ingestion.theses.fetch_missing import fetch_missing_theses_by_nnt

    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        return asyncio.run(
            fetch_missing_theses_by_nnt(conn, ctx.logger, retry_after_days=retry_after_days)
        )


def _run_fetch_missing_doi(ctx: PhaseContext, target: str) -> PhaseMetrics:
    doi_search = ADAPTERS[Source(target)].doi_search
    assert doi_search is not None, f"{target} : source interrogeable par DOI sans recherche"
    search = doi_search()
    options = ctx.options
    with ctx.open_tx() as conn:
        retry_after_days = delay(conn, ConfigKey.FETCH_MISSING_RETRY_AFTER_DAYS)
        limit = cap(conn, ConfigKey.FETCH_MISSING_MAX_PER_SOURCE)
        years = window_years(conn, start_year=options.start_year, year=options.year)
        return asyncio.run(
            fetch_missing_doi(
                conn,
                search,
                ctx.logger,
                retry_after_days=retry_after_days,
                limit=limit,
                years=years,
            )
        )
