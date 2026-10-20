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
    libelle: str | None = None
    # Échecs consécutifs avant que le circuit-breaker de la source coupe. `None` : seuil par défaut.
    threshold: int | None = None
    # Condition d'exécution, évaluée avant l'accès à la source. Un nœud écarté rend des métriques vides et n'écrit rien.
    when: Callable[[PhaseContext], bool] | None = None


def run_nodes(
    group: str,
    steps: Mapping[str, NodeStep],
    ctx: PhaseContext,
    *,
    parallel: RunParallel = run_parallel,
) -> dict[str, PhaseMetrics]:
    """Exécute les nœuds de `group` dans l'ordre du graphe et rend leurs métriques, par nom de nœud.

    Les nœuds consécutifs d'un même lot s'exécutent ensemble par `parallel` ; leurs lignes de bilan suivent, dans l'ordre du graphe. Lève `ValueError` si `steps` ne couvre pas exactement les nœuds du groupe.
    """
    nodes = [node for node in NODES if node.group == group]
    if set(steps) != {node.name for node in nodes}:
        raise ValueError(
            f"Les étapes de {group} et ses nœuds divergent : "
            f"{set(steps) ^ {node.name for node in nodes}}"
        )
    results: dict[str, PhaseMetrics] = {node.name: PhaseMetrics() for node in nodes}
    retenus = [node for node in nodes if _retenu(steps[node.name], ctx)]
    debut = 0
    while debut < len(retenus):
        fin = debut + 1
        lot = retenus[debut].lot
        while lot is not None and fin < len(retenus) and retenus[fin].lot == lot:
            fin += 1
        precedente = steps[retenus[debut - 1].name].section if debut else None
        section = steps[retenus[debut].name].section
        if section is not None and section != precedente:
            etape(ctx.logger, section)
        tranche = retenus[debut:fin]
        if len(tranche) == 1:
            node = tranche[0]
            results[node.name] = _execute(node, steps[node.name], group, ctx)
        else:
            results.update(
                parallel(
                    {
                        node.name: partial(_execute, node, steps[node.name], group, ctx)
                        for node in tranche
                    }
                )
            )
        for index in range(debut, fin):
            node = retenus[index]
            suivante = steps[retenus[index + 1].name].section if index + 1 < len(retenus) else None
            _write_lines(node, steps[node.name], results[node.name], suivante, ctx)
        debut = fin
    return results


def _write_lines(
    node: Node, step: NodeStep, metrics: PhaseMetrics, suivante: str | None, ctx: PhaseContext
) -> None:
    """Écrit la ligne de bilan du nœud, lance sa maintenance et écrit une ligne par opération."""
    lignes = [
        *([(step.libelle, _bilan(metrics))] if step.libelle is not None else []),
        *_maintain(node, ctx),
    ]
    for rang, (libelle, bilan) in enumerate(lignes):
        if step.section is None:
            ctx.logger.info("%s : %s", libelle, bilan, extra={"detail": True})
            continue
        dernier = step.section != suivante and rang == len(lignes) - 1
        ctx.logger.info("%s%s : %s", DERNIERE_BRANCHE if dernier else BRANCHE, libelle, bilan)


def _maintain(node: Node, ctx: PhaseContext) -> list[tuple[str, str]]:
    """Lance la maintenance du nœud et rend une ligne de journal par opération. `VACUUM FULL` dans un mode qui le demande."""
    lignes = []
    for operation in node.maintenance:
        if operation.startswith("VACUUM ") and ctx.options.policy.vacuum_full:
            operation = operation.replace("VACUUM", "VACUUM FULL", 1)
        t0 = time.perf_counter()
        ctx.maintain(operation)
        lignes.append((operation, f"{time.perf_counter() - t0:.1f}s"))
    return lignes


def _retenu(step: NodeStep, ctx: PhaseContext) -> bool:
    return step.when is None or step.when(ctx)


def _execute(node: Node, step: NodeStep, group: str, ctx: PhaseContext) -> PhaseMetrics:
    """Exécute le nœud et range sa durée dans `duration_s`."""
    t0 = time.perf_counter()
    if node.network is None:
        metrics = step.run(ctx, None)
    else:
        metrics = access_source(
            node.network,
            lambda breaker: step.run(ctx, breaker),
            phase=group,
            logger=ctx.logger,
            threshold=step.threshold,
        )
    metrics.duration_s = round(time.perf_counter() - t0, 1)
    return metrics


def _bilan(metrics: PhaseMetrics) -> str:
    """Bilan d'un nœud : son résumé, ou ce qui l'a empêché de travailler."""
    if metrics.resume is not None:
        return metrics.resume
    if any(s["code"] == "source_unconfigured" for s in metrics.signals):
        return "sautée, accès non configuré"
    if metrics.signals:
        return "interrompue"
    return "rien à faire"


@dataclass(frozen=True)
class NodePhase:
    """Phase d'un seul nœud, `node`, dont `phase` fait le travail."""

    node: str
    phase: Phase

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        group = self.node.partition(".")[0]
        step = NodeStep(lambda ctx, _breaker: self.phase.run(ctx))
        return run_nodes(group, {self.node: step}, ctx)[self.node]
