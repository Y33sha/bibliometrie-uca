"""Exécution des phases et de leurs tâches (`pipeline.graph`).

Une tâche déclare sa fonction d'exécution et son affichage. L'exécuteur ouvre la section de la tâche, titre de son étape de premier niveau ou `Task.section`, puis l'exécute. Une tâche réseau passe par l'accès à sa source. L'exécuteur range ensuite la durée de la tâche dans le contexte, écrit sa ligne de bilan suivie de ses notes (`PhaseMetrics.notes`) et lance sa maintenance.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from functools import partial
from itertools import pairwise

from pipeline.graph import Phase, Step, Task, leaves
from pipeline.runtime.access_source import access_source
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import (
    BRANCH,
    BRANCH_CONTINUATION,
    LAST_BRANCH,
    nothing_to_do,
    open_section,
)
from pipeline.runtime.observability.metrics import PhaseMetrics, ReportNote
from pipeline.runtime.parallel import run_parallel


def execute_tasks(children: Sequence[Step | Task], ctx: PhaseContext) -> dict[str, PhaseMetrics]:
    """Exécute les tâches de `children` dans leur ordre et renvoie les métriques des tâches exécutées, par nom de tâche. Une tâche écartée par sa condition est absente du résultat.

    Les tâches consécutives d'un même groupe parallèle s'exécutent ensemble (`run_parallel`). Leurs lignes de bilan suivent, dans l'ordre des tâches (`_Tree`).
    """
    selected = [task for task in leaves(children) if task.when is None or task.when(ctx)]
    tree = _Tree(_sections(children), selected, ctx.logger)
    results: dict[str, PhaseMetrics] = {}
    for block in _blocks(selected):
        tree.open_block(block)
        results.update(_execute_block(block, ctx))
        for task in block:
            metrics = results[task.name]
            ctx.task_durations[task.name] = metrics.duration_s or 0.0
            silent = _silent(task, metrics)
            tree.write(
                task,
                None if silent else _report(task, metrics),
                metrics.notes,
                _maintain(task, ctx),
                silent=silent,
            )
    return results


class _Tree:
    """Arborescence du journal d'une phase : titres de section, branches des lignes de bilan, fermeture des sections.

    Le titre de section d'un bloc d'une seule section précède son exécution : les lignes écrites par ses tâches et ses barres d'avancement viennent sous lui. Un bloc de plusieurs sections ouvre chacune au moment d'écrire ses lignes. La dernière ligne d'une section, ou de la phase, prend `LAST_BRANCH`. Une section aux tâches toutes silencieuses se ferme sur « Rien à faire » : son titre a ainsi une ligne sous lui.

    Une tâche sans section écrit sous le titre courant, et ses lignes vont au seul journal : une barre d'avancement en tient lieu en terminal, ou la ligne double celles écrites par la tâche.
    """

    def __init__(
        self, sections: Mapping[str, str | None], tasks: Sequence[Task], logger: logging.Logger
    ) -> None:
        self._sections = sections
        self._logger = logger
        self._closing = {
            task.name: sections[following.name] != sections[task.name]
            for task, following in pairwise(tasks)
        }
        """Par nom de tâche : la tâche suivante est d'une autre section. La dernière tâche ferme la phase, absente ici."""
        self._opened: str | None = None
        self._quiet = True
        """Les tâches de la section ouverte sont toutes silencieuses."""

    def open_block(self, block: Sequence[Task]) -> None:
        """Ouvre la section d'un bloc avant son exécution, si toutes ses tâches en partagent une."""
        sections = {self._sections[task.name] for task in block}
        if len(sections) == 1:
            self._open(sections.pop())

    def write(
        self,
        task: Task,
        report: str | None,
        notes: Sequence[ReportNote],
        maintenance: Sequence[str],
        *,
        silent: bool,
    ) -> None:
        """Écrit sous la section de la tâche sa ligne de bilan, s'il y en a une, suivie de ses notes, puis une ligne par opération de maintenance. Ferme la section après sa dernière tâche.

        Le trait vertical de la branche longe les notes, sauf sous la dernière ligne de la section. Les notes restent visibles au terminal, même sous une ligne de bilan masquée : la barre d'avancement en tient lieu.
        """
        section = self._sections[task.name]
        self._open(section)
        self._opened = section
        self._quiet = self._quiet and silent
        closing = self._closing.get(task.name, True)
        lines: list[tuple[str, Sequence[ReportNote]]] = [
            *([(report, notes)] if report is not None else []),
            *((line, ()) for line in maintenance),
        ]
        for rank, (line, line_notes) in enumerate(lines):
            last = closing and rank == len(lines) - 1
            self._logger.info(
                "%s%s", LAST_BRANCH if last else BRANCH, line, extra={"detail": section is None}
            )
            margin = " " * len(LAST_BRANCH) if last else BRANCH_CONTINUATION
            for note in line_notes:
                self._logger.info("%s%s", margin, note.text)
                for case in note.cases:
                    self._logger.info("%s%s", margin, case, extra={"detail": True})
        if section is not None and closing and self._quiet:
            nothing_to_do(self._logger)

    def _open(self, section: str | None) -> None:
        """Écrit le titre de `section`, sauf section déjà ouverte ou absente."""
        if section is not None and section != self._opened:
            open_section(self._logger, section)
            self._opened = section
            self._quiet = True


def _sections(children: Sequence[Step | Task]) -> dict[str, str | None]:
    """Renvoie la section de chaque tâche, par nom de tâche : celle de l'étape de premier niveau qui la contient, à défaut la sienne."""
    sections: dict[str, str | None] = {}
    for child in children:
        step_section = child.section if isinstance(child, Step) else None
        for task in leaves((child,)):
            sections[task.name] = step_section if step_section is not None else task.section
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
    """Vrai si la tâche reste silencieuse : `silent_when_empty`, sans élément traité, erreur ni signal."""
    return (
        task.silent_when_empty and metrics.total == 0 and not metrics.errors and not metrics.signals
    )


def _report(task: Task, metrics: PhaseMetrics) -> str | None:
    """Renvoie la ligne de bilan de la tâche : son libellé suivi de son bilan, ou, sans libellé, sa ligne de bilan (`PhaseMetrics.report`). `None` : la tâche écrit elle-même ses lignes."""
    if task.label is not None:
        return f"{task.label} : {_outcome(metrics)}"
    return metrics.report


def _maintain(task: Task, ctx: PhaseContext) -> list[str]:
    """Lance la maintenance de la tâche et renvoie une ligne de journal par opération. `VACUUM` devient `VACUUM FULL` dans un mode qui le demande."""
    lines = []
    for operation in task.maintenance:
        if operation.startswith("VACUUM ") and ctx.options.policy.vacuum_full:
            operation = operation.replace("VACUUM", "VACUUM FULL", 1)
        t0 = time.perf_counter()
        ctx.maintain(operation)
        lines.append(f"{operation} : {time.perf_counter() - t0:.1f}s")
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


_PARTIAL = frozenset({"harvest_error", "harvest_incomplete"})
"""Signaux d'une tâche allée à son terme sur une partie de son travail."""


def _outcome(metrics: PhaseMetrics) -> str:
    """Renvoie le bilan d'une tâche : sa ligne de bilan, l'obstacle à son exécution, ou ses compteurs. Un signal d'exécution partielle (`_PARTIAL`) laisse les compteurs, erreurs comprises."""
    if metrics.report is not None:
        return metrics.report
    codes = {s["code"] for s in metrics.signals}
    if "source_unconfigured" in codes:
        return "sautée, accès non configuré"
    if codes - _PARTIAL:
        return "interrompue"
    return metrics.as_summary()


def run_phase(phase: Phase, ctx: PhaseContext) -> PhaseMetrics:
    """Exécute les tâches d'une phase et renvoie les métriques de la phase.

    Une phase à `total_line` qui a exécuté plusieurs tâches se termine par la ligne « Total », somme de leurs bilans.
    """
    if phase.when is not None and not phase.when(ctx):
        ctx.logger.info("%sSautée", LAST_BRANCH)
        return PhaseMetrics()
    if phase.check is not None:
        phase.check(ctx)
    by_task = execute_tasks(phase.children, ctx)
    if phase.assemble is not None:
        metrics = phase.assemble(by_task)
    else:
        metrics = PhaseMetrics()
        for task_metrics in by_task.values():
            metrics.merge(task_metrics)
    if phase.total_line and len(by_task) > 1:
        ctx.logger.info("")
        ctx.logger.info("Total : %s", metrics.as_summary())
    return metrics
