"""Compte rendu d'une exécution de phase du pipeline : statut, signaux et métriques. La table `pipeline_phase_executions` le conserve."""

from collections.abc import Iterable
from enum import StrEnum
from typing import TypedDict


class PhaseStatus(StrEnum):
    """Statut d'une exécution de phase, et niveau d'un signal, du moins grave au plus grave. `ERROR` signale une exception, `WARNING` une interruption ou des signaux."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


def worst_status(statuses: Iterable[PhaseStatus]) -> PhaseStatus:
    """Renvoie le statut le plus grave, ou `OK` pour une liste vide."""
    order = list(PhaseStatus)
    return max(statuses, key=order.index, default=PhaseStatus.OK)


class Signal(TypedDict):
    """Fait notable remonté par une phase : source indisponible, série de réponses 429, conflit d'identifiant…"""

    level: PhaseStatus
    code: str
    """Clé de regroupement des signaux."""
    message: str
    """Texte affiché tel quel."""


class PhaseMetricsPayload(TypedDict):
    """Compteurs et durée d'une exécution de phase, sous forme JSON."""

    new: int
    updated: int
    unchanged: int
    total: int
    errors: int
    extras: dict[str, int]
    duration_s: float
