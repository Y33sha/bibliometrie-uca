"""Exécution des tâches d'une phase, dans l'ordre du graphe (`pipeline.graph`).

Une phase fournit, pour chacune de ses tâches, un `TaskStep` : la fonction qui l'exécute, et pour une tâche qui tient une ligne du journal, sa section et son libellé. L'exécuteur ouvre la section quand elle change, exécute la tâche par l'accès à sa source si elle en déclare une (`network`) et mesure sa durée, écrit sa ligne de bilan, puis lance sa maintenance (`maintenance`). Une tâche sans libellé écrit elle-même ses lignes.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial

from pipeline.graph import TASKS, Task
from pipeline.runtime.access_source import access_source
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.parallel import RunParallel, run_parallel

type TaskRun = Callable[[PhaseContext], PhaseMetrics]
"""Exécute une tâche dans le contexte de sa phase."""


@dataclass(frozen=True)
class TaskStep:
    """Ce que l'exécuteur sait d'une tâche en plus du graphe."""

    run: TaskRun
    # Titre de la sous-étape que la tâche ouvre. `None` : la tâche écrit sous le titre courant.
    section: str | None = None
    # Libellé de la ligne de bilan. `None` : la tâche écrit elle-même ses lignes.
    label: str | None = None
    # La tâche affiche une barre d'avancement en terminal : sa ligne de bilan va au seul journal.
    progress_bar: bool = False
    # Échecs consécutifs avant que le circuit-breaker de la source coupe. `None` : seuil par défaut.
    threshold: int | None = None
    # Débit de la source en requêtes par seconde. `None` : celui du profil de la source, s'il y en a un.
    max_per_second: float | None = None
    # Condition d'exécution, évaluée avant l'accès à la source. Une tâche écartée rend des métriques vides et n'écrit rien.
    when: Callable[[PhaseContext], bool] | None = None


def run_tasks(
    phase: str,
    steps: Mapping[str, TaskStep],
    ctx: PhaseContext,
    *,
    parallel: RunParallel = run_parallel,
) -> dict[str, PhaseMetrics]:
    """Exécute les tâches de `phase` dans l'ordre du graphe et rend leurs métriques, par nom de tâche.

    Les tâches consécutives d'un même groupe parallèle s'exécutent ensemble par `parallel` ; leurs lignes de bilan suivent, dans l'ordre du graphe. Lève `ValueError` si `steps` ne couvre pas exactement les tâches de la phase.
    """
    tasks = [task for task in TASKS if task.phase == phase]
    if set(steps) != {task.name for task in tasks}:
        raise ValueError(
            f"Les étapes de {phase} et ses tâches divergent : "
            f"{set(steps) ^ {task.name for task in tasks}}"
        )
    results: dict[str, PhaseMetrics] = {task.name: PhaseMetrics() for task in tasks}
    selected = [task for task in tasks if _selected(steps[task.name], ctx)]
    start = 0
    while start < len(selected):
        end = start + 1
        group = selected[start].parallel_group
        while group is not None and end < len(selected) and selected[end].parallel_group == group:
            end += 1
        previous_section = steps[selected[start - 1].name].section if start else None
        section = steps[selected[start].name].section
        if section is not None and section != previous_section:
            step(ctx.logger, section)
        chunk = selected[start:end]
        if len(chunk) == 1:
            task = chunk[0]
            results[task.name] = _execute(task, steps[task.name], phase, ctx)
        else:
            results.update(
                parallel(
                    {
                        task.name: partial(_execute, task, steps[task.name], phase, ctx)
                        for task in chunk
                    }
                )
            )
        for index in range(start, end):
            task = selected[index]
            next_section = (
                steps[selected[index + 1].name].section if index + 1 < len(selected) else None
            )
            _write_lines(task, steps[task.name], results[task.name], next_section, ctx)
        start = end
    return results


def _write_lines(
    task: Task, step: TaskStep, metrics: PhaseMetrics, next_section: str | None, ctx: PhaseContext
) -> None:
    """Écrit la ligne de bilan de la tâche, lance sa maintenance et écrit une ligne par opération."""
    lines = [
        *([(step.label, _outcome(metrics))] if step.label is not None else []),
        *_maintain(task, ctx),
    ]
    for rank, (label, outcome) in enumerate(lines):
        last = step.section != next_section and rank == len(lines) - 1
        ctx.logger.info(
            "%s%s : %s",
            LAST_BRANCH if last else BRANCH,
            label,
            outcome,
            extra={"detail": step.section is None or (step.progress_bar and rank == 0)},
        )


def _maintain(task: Task, ctx: PhaseContext) -> list[tuple[str, str]]:
    """Lance la maintenance de la tâche et rend une ligne de journal par opération. `VACUUM FULL` dans un mode qui le demande."""
    lines = []
    for operation in task.maintenance:
        if operation.startswith("VACUUM ") and ctx.options.policy.vacuum_full:
            operation = operation.replace("VACUUM", "VACUUM FULL", 1)
        t0 = time.perf_counter()
        ctx.maintain(operation)
        lines.append((operation, f"{time.perf_counter() - t0:.1f}s"))
    return lines


def _selected(step: TaskStep, ctx: PhaseContext) -> bool:
    return step.when is None or step.when(ctx)


def _execute(task: Task, step: TaskStep, phase: str, ctx: PhaseContext) -> PhaseMetrics:
    """Exécute la tâche et range sa durée dans `duration_s`."""
    t0 = time.perf_counter()
    if task.network is None:
        metrics = step.run(ctx)
    else:
        metrics = access_source(
            task.network,
            partial(step.run, ctx),
            phase=phase,
            logger=ctx.logger,
            credentials_missing=ctx.credentials_missing,
            threshold=step.threshold,
            max_per_second=step.max_per_second,
        )
    metrics.duration_s = round(time.perf_counter() - t0, 1)
    return metrics


def _outcome(metrics: PhaseMetrics) -> str:
    """Bilan d'une tâche : sa ligne de bilan, ce qui l'a empêché de travailler, ou ses compteurs."""
    if metrics.report is not None:
        return metrics.report
    if any(s["code"] == "source_unconfigured" for s in metrics.signals):
        return "sautée, accès non configuré"
    if metrics.signals:
        return "interrompue"
    return metrics.as_summary()


@dataclass(frozen=True)
class SingleTaskPhase:
    """Phase d'une seule tâche, `task`, dont `phase` fait le travail. `label` donne à la tâche une ligne de bilan, écrite au seul journal."""

    task: str
    phase: Phase
    label: str | None = None

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        step = TaskStep(self.phase.run, label=self.label)
        return run_tasks(self.task.partition(".")[0], {self.task: step}, ctx)[self.task]
