"""Exécution des tâches d'une phase, dans l'ordre du graphe (`pipeline.graph`).

Une tâche déclare sa fonction d'exécution et son affichage, ou les reçoit d'un `TaskStep`. L'exécuteur ouvre la section de la tâche, puis l'exécute. Une tâche réseau passe par l'accès à sa source. L'exécuteur range ensuite la durée de la tâche dans le contexte, écrit sa ligne de bilan et lance sa maintenance.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial

from pipeline.graph import Phase as GraphPhase, Task, TaskRun, phase_tasks
from pipeline.runtime.access_source import access_source
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, nothing_to_do, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.parallel import RunParallel, run_parallel


@dataclass(frozen=True)
class TaskStep:
    """Description d'une tâche pour l'exécuteur, en complément du graphe."""

    run: TaskRun
    section: str | None = None
    """Titre de la sous-étape ouverte par la tâche. `None` : la tâche écrit sous le titre courant."""
    label: str | None = None
    """Libellé de la ligne de bilan. `None` : la tâche écrit elle-même ses lignes."""
    progress_bar: bool = False
    """La tâche affiche une barre d'avancement en terminal, donc sa ligne de bilan va seulement au journal."""
    threshold: int | None = None
    """Échecs consécutifs avant la coupure du circuit-breaker de la source. `None` : seuil par défaut."""
    when: Callable[[PhaseContext], bool] | None = None
    """Condition d'exécution, évaluée avant l'accès à la source. Une tâche écartée renvoie des métriques vides et n'écrit rien."""
    silent_when_empty: bool = False
    """La tâche n'écrit rien sans élément traité : `total` nul, sans signal."""


def run_tasks(
    phase: str,
    steps: Mapping[str, TaskStep],
    ctx: PhaseContext,
    *,
    parallel: RunParallel = run_parallel,
) -> dict[str, PhaseMetrics]:
    """Exécute les tâches de `phase` déclarées dans `TASKS`, chacune par son étape dans `steps`, et renvoie leurs métriques, par nom de tâche. Une tâche écartée par sa condition reçoit des métriques vides.

    Raises:
        ValueError: `steps` diffère des tâches de la phase.
    """
    tasks = phase_tasks(phase)
    if set(steps) != {task.name for task in tasks}:
        raise ValueError(
            f"Les étapes de {phase} et ses tâches divergent : "
            f"{set(steps) ^ {task.name for task in tasks}}"
        )
    executed = execute_tasks(
        [
            replace(
                task,
                run=steps[task.name].run,
                section=steps[task.name].section,
                label=steps[task.name].label,
                progress_bar=steps[task.name].progress_bar,
                threshold=steps[task.name].threshold,
                when=steps[task.name].when,
                silent_when_empty=steps[task.name].silent_when_empty,
            )
            for task in tasks
        ],
        ctx,
        parallel=parallel,
    )
    return {task.name: executed.get(task.name, PhaseMetrics()) for task in tasks}


def execute_tasks(
    tasks: Sequence[Task], ctx: PhaseContext, *, parallel: RunParallel = run_parallel
) -> dict[str, PhaseMetrics]:
    """Exécute `tasks` dans leur ordre et renvoie les métriques des tâches exécutées, par nom de tâche. Une tâche écartée par sa condition est absente du résultat.

    Les tâches consécutives d'un même groupe parallèle s'exécutent ensemble par `parallel`. Leurs lignes de bilan suivent, dans l'ordre des tâches.
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
            results.update(parallel({task.name: partial(_execute, task, ctx) for task in chunk}))
        for index in range(start, end):
            task = selected[index]
            ctx.task_durations[task.name] = results[task.name].duration_s or 0.0
            next_section = selected[index + 1].section if index + 1 < len(selected) else None
            _write_lines(task, results[task.name], next_section, ctx)
            if task.section is not None and task.section != next_section:
                _close_if_silent([t for t in selected if t.section == task.section], results, ctx)
        start = end
    return results


def _close_if_silent(
    tasks: list[Task], results: Mapping[str, PhaseMetrics], ctx: PhaseContext
) -> None:
    """Ferme sur « Rien à faire » la section des tâches `tasks` quand toutes sont silencieuses : le titre a ainsi une ligne sous lui."""
    if all(
        task.silent_when_empty and results[task.name].total == 0 and not results[task.name].signals
        for task in tasks
    ):
        nothing_to_do(ctx.logger)


def _write_lines(
    task: Task, metrics: PhaseMetrics, next_section: str | None, ctx: PhaseContext
) -> None:
    """Écrit la ligne de bilan de la tâche, lance sa maintenance et écrit une ligne par opération."""
    lines = [
        *([(task.label, _outcome(metrics))] if task.label is not None else []),
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
    assert task.run is not None
    t0 = time.perf_counter()
    if task.network is None:
        metrics = task.run(ctx)
    else:
        metrics = access_source(
            task.network,
            partial(task.run, ctx),
            phase=task.phase,
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


def run_phase(phase: GraphPhase, ctx: PhaseContext) -> PhaseMetrics:
    """Exécute les tâches d'une phase et renvoie les métriques de la phase."""
    if phase.build is not None:
        return phase.build().run(ctx)
    if phase.check is not None:
        phase.check(ctx)
    by_task = execute_tasks(phase.tasks, ctx)
    if phase.assemble is not None:
        return phase.assemble(by_task)
    metrics = PhaseMetrics()
    for task_metrics in by_task.values():
        metrics.merge(task_metrics)
    return metrics
