"""Exécution des phases et de leurs tâches (`pipeline.graph`).

Une tâche déclare sa fonction d'exécution et son affichage. L'exécuteur ouvre la section de la tâche, titre de son étape de premier niveau ou `Task.section`, puis l'exécute. Une tâche réseau passe par l'accès à sa source. L'exécuteur range ensuite la durée de la tâche dans le contexte, écrit sa ligne de bilan et lance sa maintenance.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from functools import partial
from itertools import pairwise

from pipeline.graph import Phase, Step, Task, leaves
from pipeline.runtime.access_source import access_source
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, nothing_to_do, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.parallel import run_parallel


def execute_tasks(children: Sequence[Step | Task], ctx: PhaseContext) -> dict[str, PhaseMetrics]:
    """Exécute les tâches de `children` dans leur ordre et renvoie les métriques des tâches exécutées, par nom de tâche. Une tâche écartée par sa condition est absente du résultat.

    Les tâches consécutives d'un même groupe parallèle s'exécutent ensemble (`run_parallel`). Leurs lignes de bilan suivent, dans l'ordre des tâches. Le titre de section d'un bloc d'une seule section précède son exécution. Un bloc de plusieurs sections ouvre chacune au moment d'écrire ses lignes.
    """
    sections = _sections(children)
    selected = [task for task in leaves(children) if task.when is None or task.when(ctx)]
    next_sections = {task.name: sections[following.name] for task, following in pairwise(selected)}
    results: dict[str, PhaseMetrics] = {}
    opened = None
    for block in _blocks(selected):
        block_sections = {sections[task.name] for task in block}
        section = sections[block[0].name]
        if len(block_sections) == 1 and section is not None and section != opened:
            step(ctx.logger, section)
            opened = section
        results.update(_execute_block(block, ctx))
        for task in block:
            ctx.task_durations[task.name] = results[task.name].duration_s or 0.0
            section, next_section = sections[task.name], next_sections.get(task.name)
            if section is not None and section != opened:
                step(ctx.logger, section)
            opened = section
            _write_lines(task, results[task.name], section, next_section, ctx)
            if section is not None and section != next_section:
                _close_if_silent([t for t in selected if sections[t.name] == section], results, ctx)
    return results


def _sections(children: Sequence[Step | Task]) -> dict[str, str | None]:
    """Renvoie le titre de section de chaque tâche, par nom de tâche : celui de l'étape de premier niveau qui la contient, à défaut sa `section`."""
    sections: dict[str, str | None] = {}
    for child in children:
        label = child.label if isinstance(child, Step) else None
        for task in leaves((child,)):
            sections[task.name] = label if label is not None else task.section
    return sections


def _blocks(tasks: Sequence[Task]) -> list[list[Task]]:
    """Découpe `tasks` en blocs exécutés ensemble : une tâche seule, ou les tâches consécutives d'un même groupe parallèle."""
    blocks: list[list[Task]] = []
    for task in tasks:
        group = task.parallel_group
        if blocks and group is not None and group == blocks[-1][0].parallel_group:
            blocks[-1].append(task)
        else:
            blocks.append([task])
    return blocks


def _execute_block(block: list[Task], ctx: PhaseContext) -> dict[str, PhaseMetrics]:
    """Exécute un bloc de tâches et renvoie leurs métriques par nom de tâche. Les tâches d'une même source s'enchaînent dans une file, les files s'exécutent en parallèle."""
    lanes: dict[str | None, list[Task]] = {}
    for task in block:
        lanes.setdefault(task.network, []).append(task)
    if len(lanes) == 1:
        return _execute_lane(block, ctx)
    results: dict[str, PhaseMetrics] = {}
    for lane_results in run_parallel(
        {str(source): partial(_execute_lane, lane, ctx) for source, lane in lanes.items()}
    ).values():
        results.update(lane_results)
    return results


def _execute_lane(tasks: list[Task], ctx: PhaseContext) -> dict[str, PhaseMetrics]:
    """Exécute des tâches l'une après l'autre et renvoie leurs métriques par nom de tâche."""
    return {task.name: _execute(task, ctx) for task in tasks}


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
    task: Task,
    metrics: PhaseMetrics,
    section: str | None,
    next_section: str | None,
    ctx: PhaseContext,
) -> None:
    """Écrit la ligne de bilan de la tâche, sauf tâche silencieuse, lance sa maintenance et écrit une ligne par opération."""
    has_report = task.label is not None and not _silent(task, metrics)
    lines = [
        *([(task.label, _outcome(metrics))] if has_report else []),
        *_maintain(task, ctx),
    ]
    for rank, (label, outcome) in enumerate(lines):
        last = section != next_section and rank == len(lines) - 1
        ctx.logger.info(
            "%s%s : %s",
            LAST_BRANCH if last else BRANCH,
            label,
            outcome,
            extra={"detail": section is None or (task.progress_bar and rank == 0)},
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
    """Renvoie le bilan d'une tâche : sa ligne de bilan, l'obstacle à son exécution, ou ses compteurs. Un signal d'une erreur partielle (`harvest_error`) laisse les compteurs, erreurs comprises."""
    if metrics.report is not None:
        return metrics.report
    codes = {s["code"] for s in metrics.signals}
    if "source_unconfigured" in codes:
        return "sautée, accès non configuré"
    if codes - {"harvest_error"}:
        return "interrompue"
    return metrics.as_summary()


def run_phase(phase: Phase, ctx: PhaseContext) -> PhaseMetrics:
    """Exécute les tâches d'une phase et renvoie les métriques de la phase."""
    if phase.when is not None and not phase.when(ctx.options):
        ctx.logger.info("%sSautée en mode %s", LAST_BRANCH, ctx.options.mode)
        return PhaseMetrics()
    if phase.check is not None:
        phase.check(ctx)
    by_task = execute_tasks(phase.children, ctx)
    if phase.assemble is not None:
        return phase.assemble(by_task)
    metrics = PhaseMetrics()
    for task_metrics in by_task.values():
        metrics.merge(task_metrics)
    return metrics
