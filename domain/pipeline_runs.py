"""Compte rendu d'une exécution de phase du pipeline : statut, signaux et métriques.

Le pipeline le produit, `infrastructure/observability/` l'enregistre dans `pipeline_phase_executions`, et l'API le relit pour la page des exécutions.

Le statut et les signaux disent la santé du run : `error` est décidé par l'orchestrateur sur exception, `warning` et les signaux sont remontés par la phase elle-même (source indisponible, série de 429, conflit d'identifiant…).
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import TypedDict


class PhaseStatus(StrEnum):
    """Statut d'une exécution de phase, et niveau d'un signal. Les membres sont rangés du moins grave au plus grave."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


def worst_status(statuses: Iterable[PhaseStatus]) -> PhaseStatus:
    """Statut le plus grave parmi `statuses` ; `OK` sans statut. C'est le statut d'un run."""
    order = list(PhaseStatus)
    return max(statuses, key=order.index, default=PhaseStatus.OK)


class Signal(TypedDict):
    """Un fait notable remonté par une phase.

    `level` aligne la couleur de la phase (`warning` ou `error`), `code` permet le regroupement, `message` est lisible tel quel.
    """

    level: PhaseStatus
    code: str
    message: str


class PhaseMetricsPayload(TypedDict):
    """Sérialisation JSON de `pipeline.runtime.observability.metrics.PhaseMetrics`, durée d'exécution mesurée par l'orchestrateur comprise."""

    new: int
    updated: int
    unchanged: int
    total: int
    errors: int
    extras: dict[str, int]
    duration_s: float
