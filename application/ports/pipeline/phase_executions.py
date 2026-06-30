"""Value objects d'une exécution de phase du pipeline (chantier observabilité).

Une exécution de phase = une ligne de `pipeline_phase_executions`. Ces structures
circulent entre la capture (orchestrateur `run_pipeline.py`), la persistance
(`infrastructure/observability/`) et la lecture (API). Placées en zone neutre
`application/ports/` : ni I/O ni dépendance framework.

Le statut et les signaux portent la santé du run : `error` est décidé par
l'orchestrateur sur exception, `warning` et les signaux sont remontés par la
phase elle-même (source indisponible, série de 429, conflit d'identité…).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Literal, TypedDict

PhaseStatus = Literal["ok", "warning", "error"]


class Signal(TypedDict):
    """Un fait notable remonté par une phase.

    `level` aligne la couleur de la phase (`warning` ou `error`), `code` permet le
    regroupement, `message` est lisible tel quel.
    """

    level: PhaseStatus
    code: str
    message: str


class PhaseMetricsPayload(TypedDict):
    """Sérialisation JSON de `application.pipeline.metrics.PhaseMetrics`, durée
    d'exécution mesurée par l'orchestrateur comprise."""

    new: int
    updated: int
    unchanged: int
    total: int
    errors: int
    extras: dict[str, int]
    duration_s: float


@dataclass
class PhaseExecution:
    """Une exécution de phase, prête à persister et relue depuis la base."""

    run_id: int
    phase: str
    started_at: datetime.datetime
    ended_at: datetime.datetime
    mode: str
    sources: list[str]
    status: PhaseStatus
    metrics: PhaseMetricsPayload
    signals: list[Signal] = field(default_factory=list)
    # Indicateurs sur-mesure remontés par la phase (conventions `summary`, `table`,
    # `lines`, `matrix` ; cf. `interfaces/frontend/.../phase-views.ts`).
    details: dict[str, object] = field(default_factory=dict)
