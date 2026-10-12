"""Exécution des nœuds d'une phase, dans l'ordre du graphe (`pipeline.graph`).

Une phase fournit, pour chacun de ses nœuds, un `NodeStep` : la fonction qui l'exécute, sa section et son libellé dans le journal. L'exécuteur ouvre la section quand elle change, exécute le nœud par l'accès à sa source s'il en déclare une (`network`), puis écrit sa ligne de bilan.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pipeline.graph import NODES, Node
from pipeline.ingestion.http.access_source import access_source
from pipeline.ingestion.http.circuit_breaker import SourceCircuitBreaker
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, etape
from pipeline.runtime.observability.metrics import PhaseMetrics

type NodeRun = Callable[[SourceCircuitBreaker | None], PhaseMetrics]
"""Exécute un nœud. Reçoit le circuit-breaker de sa source, `None` pour un nœud sans source."""


@dataclass(frozen=True)
class NodeStep:
    """Ce que l'exécuteur sait d'un nœud en plus du graphe."""

    run: NodeRun
    section: str
    libelle: str
    # Échecs consécutifs avant que le circuit-breaker de la source coupe. `None` : seuil par défaut.
    threshold: int | None = None


def run_nodes(
    group: str, steps: Mapping[str, NodeStep], logger: logging.Logger
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
    results: dict[str, PhaseMetrics] = {}
    for index, node in enumerate(nodes):
        step = steps[node.name]
        if index == 0 or steps[nodes[index - 1].name].section != step.section:
            etape(logger, step.section)
        dernier = index == len(nodes) - 1 or steps[nodes[index + 1].name].section != step.section
        metrics = _execute(node, step, group, logger)
        branche = DERNIERE_BRANCHE if dernier else BRANCHE
        logger.info("%s%s : %s", branche, step.libelle, _bilan(metrics))
        results[node.name] = metrics
    return results


def _execute(node: Node, step: NodeStep, group: str, logger: logging.Logger) -> PhaseMetrics:
    if node.network is None:
        return step.run(None)
    return access_source(
        node.network, step.run, phase=group, logger=logger, threshold=step.threshold
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
