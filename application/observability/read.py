"""Calculs de lecture sur les exécutions de phase : rendement et écart de durée.

Pur, sans I/O. Le rendement rapporte le volume de la table principale produite à
celui de la table principale consommée (premières entrées de `produces` et
`consumes` du graphe des phases) ; il vaut `None` pour les phases sans entrée
locale (extraction) ou quand les observables manquent. La comparaison de durée se
fait au médian historique de la même phase, fourni par l'appelant (issu d'une
requête) ; aucun seuil n'est posé, seul le rapport est exposé pour l'affichage —
l'œil juge une phase anormalement lente.
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median

from application.pipeline.graph import PHASE_ORDER, node
from application.ports.pipeline.phase_executions import PhaseExecution


def compute_yield(execution: PhaseExecution) -> float | None:
    """Rendement = volume produit principal / volume consommé principal. `None` si
    la phase n'a pas d'entrée locale, si les observables manquent, ou si l'entrée
    est nulle."""
    if execution.phase not in PHASE_ORDER:
        return None
    graph_node = node(execution.phase)
    if not graph_node.consumes or not graph_node.produces:
        return None
    if execution.input is None or execution.output is None:
        return None
    consumed = execution.input.get(graph_node.consumes[0])
    produced = execution.output.get(graph_node.produces[0])
    if consumed is None or produced is None or consumed == 0:
        return None
    return produced / consumed


def median_duration(durations: Sequence[float]) -> float | None:
    """Médian des durées historiques d'une phase, ou `None` si l'historique est vide."""
    return float(median(durations)) if durations else None


def duration_ratio(duration_s: float, historical_median_s: float | None) -> float | None:
    """Rapport de la durée courante au médian historique (> 1 = plus lent que
    d'habitude). `None` sans historique exploitable."""
    if historical_median_s is None or historical_median_s == 0:
        return None
    return duration_s / historical_median_s
