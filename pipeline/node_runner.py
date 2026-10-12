"""Exécution des nœuds d'une phase, dans l'ordre du graphe (`pipeline.graph`).

Une phase fournit, pour chacun de ses nœuds, un `NodeStep` : la fonction qui l'exécute, et pour un nœud qui tient une ligne du journal, sa section et son libellé. L'exécuteur ouvre la section quand elle change, exécute le nœud par l'accès à sa source s'il en déclare une (`network`), écrit sa ligne de bilan, puis lance sa maintenance (`maintenance`). Un nœud sans section écrit lui-même ses lignes.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pipeline.graph import NODES, Node
from pipeline.ingestion.http.access_source import access_source
from pipeline.ingestion.http.circuit_breaker import SourceCircuitBreaker
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.modes import MODES
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, etape
from pipeline.runtime.observability.metrics import PhaseMetrics

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
    group: str, steps: Mapping[str, NodeStep], ctx: PhaseContext
) -> dict[str, PhaseMetrics]:
    """Exécute les nœuds de `group` dans l'ordre du graphe et rend leurs métriques, par nom de nœud.

    Lève `ValueError` si `steps` ne couvre pas exactement les nœuds du groupe.
    """
    nodes = [node for node in NODES if node.group == group]
    if set(steps) != {node.name for node in nodes}:
        raise ValueError(
            f"Les étapes de {group} et ses nœuds divergent : "
            f"{set(steps) ^ {node.name for node in nodes}}"
        )
    logger = ctx.logger
    results: dict[str, PhaseMetrics] = {node.name: PhaseMetrics() for node in nodes}
    retenus = [node for node in nodes if _retenu(steps[node.name], ctx)]
    for index, node in enumerate(retenus):
        step = steps[node.name]
        precedente = steps[retenus[index - 1].name].section if index else None
        suivante = steps[retenus[index + 1].name].section if index + 1 < len(retenus) else None
        if step.section is not None and step.section != precedente:
            etape(logger, step.section)
        metrics = _execute(node, step, group, ctx)
        fin_de_section = step.section != suivante
        lignes = [
            *([(step.libelle, _bilan(metrics))] if step.libelle is not None else []),
            *_maintain(node, ctx),
        ]
        for rang, (libelle, bilan) in enumerate(lignes):
            if step.section is None:
                logger.info("%s : %s", libelle, bilan, extra={"detail": True})
                continue
            dernier = fin_de_section and rang == len(lignes) - 1
            logger.info("%s%s : %s", DERNIERE_BRANCHE if dernier else BRANCHE, libelle, bilan)
        results[node.name] = metrics
    return results


def _maintain(node: Node, ctx: PhaseContext) -> list[tuple[str, str]]:
    """Lance la maintenance du nœud et rend une ligne de journal par opération. `VACUUM FULL` dans un mode qui le demande."""
    lignes = []
    for operation in node.maintenance:
        if operation.startswith("VACUUM ") and MODES[ctx.options.mode].vacuum_full:
            operation = operation.replace("VACUUM", "VACUUM FULL", 1)
        t0 = time.perf_counter()
        ctx.maintain(operation)
        lignes.append((operation, f"{time.perf_counter() - t0:.1f}s"))
    return lignes


def _retenu(step: NodeStep, ctx: PhaseContext) -> bool:
    return step.when is None or step.when(ctx)


def _execute(node: Node, step: NodeStep, group: str, ctx: PhaseContext) -> PhaseMetrics:
    if node.network is None:
        return step.run(ctx, None)
    return access_source(
        node.network,
        lambda breaker: step.run(ctx, breaker),
        phase=group,
        logger=ctx.logger,
        threshold=step.threshold,
    )


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
