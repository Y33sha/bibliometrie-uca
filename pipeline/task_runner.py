"""Exécution des phases et de leurs tâches (`pipeline.graph`).

Une tâche déclare sa fonction d'exécution et son affichage. L'exécuteur ouvre la section de la tâche, puis l'exécute. Une tâche réseau passe par l'accès à sa source. L'exécuteur range ensuite la durée de la tâche dans le contexte, écrit sa ligne de bilan et lance sa maintenance.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from functools import partial

from pipeline.graph import Phase, Task
from pipeline.runtime.access_source import access_source
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, nothing_to_do, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.parallel import run_parallel


def execute_tasks(tasks: Sequence[Task], ctx: PhaseContext) -> dict[str, PhaseMetrics]:
    """Exécute `tasks` dans leur ordre et renvoie les métriques des tâches exécutées, par nom de tâche. Une tâche écartée par sa condition est absente du résultat.

    Les tâches consécutives d'un même groupe parallèle s'exécutent ensemble (`run_parallel`). Leurs lignes de bilan suivent, dans l'ordre des tâches.
    """
    results: dict[str, PhaseMetrics] = {}
    selected = [task for task in tasks if task.when is None or task.when(ctx)]
    start = 0
    while start < len(selected):
        end = start + 1
        group = selected[start].parallel_group
        while group is not None and end < len(selected) and selected[end].parallel_group == group:
            end += 1
        previous_section = selected[start - 1].section if start else None
        section = selected[start].section
        if section is not None and section != previous_section:
            step(ctx.logger, section)
        chunk = selected[start:end]
        if len(chunk) == 1:
            results[chunk[0].name] = _execute(chunk[0], ctx)
        else:
            results.update(
                run_parallel({task.name: partial(_execute, task, ctx) for task in chunk})
            )
        for index in range(start, end):
            task = selected[index]
            ctx.task_durations[task.name] = results[task.name].duration_s or 0.0
            next_section = selected[index + 1].section if index + 1 < len(selected) else None
            _write_lines(task, results[task.name], next_section, ctx)
            if task.section is not None and task.section != next_section:
                _close_if_silent([t for t in selected if t.section == task.section], results, ctx)
        start = end
    return results


def _silent(task: Task, metrics: PhaseMetrics) -> bool:
    """Vrai si la tâche reste silencieuse : `silent_when_empty`, sans élément traité ni signal."""
    return task.silent_when_empty and metrics.total == 0 and not metrics.signals


def _close_if_silent(
    tasks: list[Task], results: Mapping[str, PhaseMetrics], ctx: PhaseContext
) -> None:
    """Ferme sur « Rien à faire » la section des tâches `tasks` quand toutes sont silencieuses : le titre a ainsi une ligne sous lui."""
    if all(_silent(task, results[task.name]) for task in tasks):
        nothing_to_do(ctx.logger)


def _write_lines(
    task: Task, metrics: PhaseMetrics, next_section: str | None, ctx: PhaseContext
) -> None:
    """Écrit la ligne de bilan de la tâche, sauf tâche silencieuse, lance sa maintenance et écrit une ligne par opération."""
    has_report = task.label is not None and not _silent(task, metrics)
    lines = [
        *([(task.label, _outcome(metrics))] if has_report else []),
        *_maintain(task, ctx),
    ]
    for rank, (label, outcome) in enumerate(lines):
        last = task.section != next_section and rank == len(lines) - 1
        ctx.logger.info(
            "%s%s : %s",
            LAST_BRANCH if last else BRANCH,
            label,
            outcome,
            extra={"detail": task.section is None or (task.progress_bar and rank == 0)},
        )


def _maintain(task: Task, ctx: PhaseContext) -> list[tuple[str, str]]:
    """Lance la maintenance de la tâche et renvoie une ligne de journal par opération. `VACUUM` devient `VACUUM FULL` dans un mode qui le demande."""
    lines = []
    for operation in task.maintenance:
        if operation.startswith("VACUUM ") and ctx.options.policy.vacuum_full:
            operation = operation.replace("VACUUM", "VACUUM FULL", 1)
        t0 = time.perf_counter()
        ctx.maintain(operation)
        lines.append((operation, f"{time.perf_counter() - t0:.1f}s"))
    return lines


def _execute(task: Task, ctx: PhaseContext) -> PhaseMetrics:
    """Exécute la tâche et range sa durée dans `duration_s`."""
    t0 = time.perf_counter()
    if task.network is None:
        metrics = task.run(ctx)
    else:
        metrics = access_source(
            task.network,
            partial(task.run, ctx),
            logger=ctx.logger,
            credentials_missing=ctx.credentials_missing,
            request_budget=ctx.request_budget,
            threshold=task.threshold,
        )
    metrics.duration_s = round(time.perf_counter() - t0, 1)
    return metrics


def _outcome(metrics: PhaseMetrics) -> str:
    """Renvoie le bilan d'une tâche : sa ligne de bilan, l'obstacle à son exécution, ou ses compteurs."""
    if metrics.report is not None:
        return metrics.report
    if any(s["code"] == "source_unconfigured" for s in metrics.signals):
        return "sautée, accès non configuré"
    if metrics.signals:
        return "interrompue"
    return metrics.as_summary()


def run_phase(phase: Phase, ctx: PhaseContext) -> PhaseMetrics:
    """Exécute les tâches d'une phase et renvoie les métriques de la phase."""
    if phase.when is not None and not phase.when(ctx.options):
        ctx.logger.info("%sSautée en mode %s", LAST_BRANCH, ctx.options.mode)
        return PhaseMetrics()
    if phase.check is not None:
        phase.check(ctx)
    by_task = execute_tasks(phase.tasks, ctx)
    if phase.assemble is not None:
        return phase.assemble(by_task)
    metrics = PhaseMetrics()
    for task_metrics in by_task.values():
        metrics.merge(task_metrics)
    return metrics
