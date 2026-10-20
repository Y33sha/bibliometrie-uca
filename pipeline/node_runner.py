"""Exécution des nœuds d'une phase, dans l'ordre du graphe (`pipeline.graph`).

Une phase fournit, pour chacun de ses nœuds, un `NodeStep` : la fonction qui l'exécute, et pour un nœud qui tient une ligne du journal, sa section et son libellé. L'exécuteur ouvre la section quand elle change, exécute le nœud par l'accès à sa source s'il en déclare une (`network`) et mesure sa durée, écrit sa ligne de bilan, puis lance sa maintenance (`maintenance`). Un nœud sans section écrit lui-même ses lignes.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial

from pipeline.graph import NODES, Node
from pipeline.http.circuit_breaker import SourceCircuitBreaker
from pipeline.runtime.access_source import access_source
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, etape
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.parallel import RunParallel, run_parallel

type NodeRun = Callable[[PhaseContext, SourceCircuitBreaker | None], PhaseMetrics]
"""Exécute un nœud. Reçoit le contexte de la phase, et le circuit-breaker de sa source (`None` pour un nœud sans source)."""


@dataclass(frozen=True)
class NodeStep:
    """Ce que l'exécuteur sait d'un nœud en plus du graphe."""

    run: NodeRun
    # Section et libellé de la ligne de bilan. `None` : le nœud écrit lui-même ses lignes.
    section: str | None = None
    label: str | None = None
    # Le nœud affiche une barre d'avancement en terminal : sa ligne de bilan va au seul journal.
    progress_bar: bool = False
    # Échecs consécutifs avant que le circuit-breaker de la source coupe. `None` : seuil par défaut.
    threshold: int | None = None
    # Condition d'exécution, évaluée avant l'accès à la source. Un nœud écarté rend des métriques vides et n'écrit rien.
    when: Callable[[PhaseContext], bool] | None = None


def run_nodes(
    phase: str,
    steps: Mapping[str, NodeStep],
    ctx: PhaseContext,
    *,
    parallel: RunParallel = run_parallel,
) -> dict[str, PhaseMetrics]:
    """Exécute les nœuds de `phase` dans l'ordre du graphe et rend leurs métriques, par nom de nœud.

    Les nœuds consécutifs d'un même groupe parallèle s'exécutent ensemble par `parallel` ; leurs lignes de bilan suivent, dans l'ordre du graphe. Lève `ValueError` si `steps` ne couvre pas exactement les nœuds de la phase.
    """
    nodes = [node for node in NODES if node.phase == phase]
    if set(steps) != {node.name for node in nodes}:
        raise ValueError(
            f"Les étapes de {phase} et ses nœuds divergent : "
            f"{set(steps) ^ {node.name for node in nodes}}"
        )
    results: dict[str, PhaseMetrics] = {node.name: PhaseMetrics() for node in nodes}
    selected = [node for node in nodes if _selected(steps[node.name], ctx)]
    start = 0
    while start < len(selected):
        end = start + 1
        group = selected[start].parallel_group
        while group is not None and end < len(selected) and selected[end].parallel_group == group:
            end += 1
        previous_section = steps[selected[start - 1].name].section if start else None
        section = steps[selected[start].name].section
        if section is not None and section != previous_section:
            etape(ctx.logger, section)
        chunk = selected[start:end]
        if len(chunk) == 1:
            node = chunk[0]
            results[node.name] = _execute(node, steps[node.name], phase, ctx)
        else:
            results.update(
                parallel(
                    {
                        node.name: partial(_execute, node, steps[node.name], phase, ctx)
                        for node in chunk
                    }
                )
            )
        for index in range(start, end):
            node = selected[index]
            next_section = (
                steps[selected[index + 1].name].section if index + 1 < len(selected) else None
            )
            _write_lines(node, steps[node.name], results[node.name], next_section, ctx)
        start = end
    return results


def _write_lines(
    node: Node, step: NodeStep, metrics: PhaseMetrics, next_section: str | None, ctx: PhaseContext
) -> None:
    """Écrit la ligne de bilan du nœud, lance sa maintenance et écrit une ligne par opération."""
    lines = [
        *([(step.label, _outcome(metrics))] if step.label is not None else []),
        *_maintain(node, ctx),
    ]
    for rank, (label, outcome) in enumerate(lines):
        if step.section is None:
            ctx.logger.info("%s : %s", label, outcome, extra={"detail": True})
            continue
        last = step.section != next_section and rank == len(lines) - 1
        ctx.logger.info(
            "%s%s : %s",
            DERNIERE_BRANCHE if last else BRANCHE,
            label,
            outcome,
            extra={"detail": step.progress_bar and rank == 0},
        )


def _maintain(node: Node, ctx: PhaseContext) -> list[tuple[str, str]]:
    """Lance la maintenance du nœud et rend une ligne de journal par opération. `VACUUM FULL` dans un mode qui le demande."""
    lines = []
    for operation in node.maintenance:
        if operation.startswith("VACUUM ") and ctx.options.policy.vacuum_full:
            operation = operation.replace("VACUUM", "VACUUM FULL", 1)
        t0 = time.perf_counter()
        ctx.maintain(operation)
        lines.append((operation, f"{time.perf_counter() - t0:.1f}s"))
    return lines


def _selected(step: NodeStep, ctx: PhaseContext) -> bool:
    return step.when is None or step.when(ctx)


def _execute(node: Node, step: NodeStep, phase: str, ctx: PhaseContext) -> PhaseMetrics:
    """Exécute le nœud et range sa durée dans `duration_s`."""
    t0 = time.perf_counter()
    if node.network is None:
        metrics = step.run(ctx, None)
    else:
        metrics = access_source(
            node.network,
            lambda breaker: step.run(ctx, breaker),
            phase=phase,
            logger=ctx.logger,
            credentials_missing=ctx.credentials_missing,
            threshold=step.threshold,
        )
    metrics.duration_s = round(time.perf_counter() - t0, 1)
    return metrics


def _outcome(metrics: PhaseMetrics) -> str:
    """Bilan d'un nœud : sa ligne de bilan, ce qui l'a empêché de travailler, ou ses compteurs."""
    if metrics.report is not None:
        return metrics.report
    if any(s["code"] == "source_unconfigured" for s in metrics.signals):
        return "sautée, accès non configuré"
    if metrics.signals:
        return "interrompue"
    return metrics.as_summary()


@dataclass(frozen=True)
class NodePhase:
    """Phase d'un seul nœud, `node`, dont `phase` fait le travail. `label` donne au nœud une ligne de bilan, écrite au seul journal."""

    node: str
    phase: Phase
    label: str | None = None

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        step = NodeStep(lambda ctx, _breaker: self.phase.run(ctx), label=self.label)
        return run_nodes(self.node.partition(".")[0], {self.node: step}, ctx)[self.node]
