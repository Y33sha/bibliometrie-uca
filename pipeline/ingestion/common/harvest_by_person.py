"""Phase `harvest_by_person` : moissonnage des sources par les identifiants des personnes à fiche RH, vers `staging`.

Une tâche par source, en parallèle, sur la plage d'années du moissonnage ou la seule année `--year`. La phase est sautée dans un mode dont la policy l'exclut (`daily`). `--sources` restreint les sources.

Le profil de chaque source liste les types d'identifiant de personne acceptés (`domain/sources/registry.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from domain.sources.registry import PERSON_SEARCHED_SOURCES, Source, source_label
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.harvester import HarvestWindow, run_harvest
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.parallel import RunParallel, run_parallel
from pipeline.task_runner import TaskRun, TaskStep, run_tasks

SearchOne = Callable[[PhaseContext, str, HarvestWindow], PhaseMetrics]


@dataclass(frozen=True)
class HarvestByPersonPhase:
    search_one: SearchOne
    run_parallel: RunParallel

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute en parallèle la tâche de chaque source retenue et assemble les métriques."""
        options = ctx.options
        if not options.policy.harvest_by_person:
            ctx.logger.info("%sSautée en mode %s", LAST_BRANCH, options.mode)
            return PhaseMetrics()
        effective = set(PERSON_SEARCHED_SOURCES) & options.sources

        def task(source: str) -> TaskRun:
            def run(ctx: PhaseContext) -> PhaseMetrics:
                window = HarvestWindow(start_year=options.start_year, year=options.year)
                return self.search_one(ctx, source, window)

            return run

        def selected(source: str) -> Callable[[PhaseContext], bool]:
            return lambda _ctx: source in effective

        by_task = run_tasks(
            "harvest_by_person",
            {
                f"harvest_by_person.{source}": TaskStep(
                    task(source),
                    label=source_label(source),
                    progress_bar=True,
                    threshold=5,
                    when=selected(source),
                )
                for source in PERSON_SEARCHED_SOURCES
            },
            ctx,
            parallel=self.run_parallel,
        )
        metrics = PhaseMetrics()
        for source_metrics in by_task.values():
            metrics.merge(source_metrics)
        return metrics


def build() -> Phase:
    def search_one(ctx: PhaseContext, source: str, window: HarvestWindow) -> PhaseMetrics:
        harvester = ADAPTERS[Source(source)].person_harvester
        assert harvester is not None, f"{source} : source cherchée par personne sans moissonneur"
        return run_harvest(ctx, "harvest_by_person", source, harvester, window)

    return HarvestByPersonPhase(search_one=search_one, run_parallel=run_parallel)
