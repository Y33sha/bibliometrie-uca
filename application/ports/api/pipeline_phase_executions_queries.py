"""Port : lectures sur les exécutions de phase du pipeline (/api/admin/pipeline/runs/*).

La liste agrège les exécutions par `run_id` (statut global = le pire des statuts de
phase). Le détail d'un run renvoie ses phases dans l'ordre d'exécution, chacune avec
son rendement et son écart de durée au médian historique, recalculés à la lecture
(cf. `application.observability.read`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from application.ports.pipeline.phase_executions import (
    ObservableVolumes,
    PhaseMetricsPayload,
    PhaseStatus,
    Signal,
)


class RunSummary(BaseModel):
    """Une ligne dans la liste des runs (agrégat des exécutions d'un même `run_id`)."""

    run_id: int
    started_at: datetime
    ended_at: datetime
    mode: str
    sources: list[str]
    status: PhaseStatus
    phase_count: int
    total_duration_s: float


class PhaseExecutionDetail(BaseModel):
    """Une exécution de phase, enrichie des valeurs recalculées à la lecture."""

    phase: str
    started_at: datetime
    ended_at: datetime
    status: PhaseStatus
    duration_s: float
    metrics: PhaseMetricsPayload
    input: ObservableVolumes | None
    output: ObservableVolumes | None
    yield_ratio: float | None
    historical_median_duration_s: float | None
    duration_ratio: float | None
    signals: list[Signal]


class RunDetail(BaseModel):
    """Détail d'un run : ses phases et les agrégats de run."""

    run_id: int
    started_at: datetime
    ended_at: datetime
    mode: str
    sources: list[str]
    status: PhaseStatus
    total_duration_s: float
    phases: list[PhaseExecutionDetail]


class PhaseExecutionsQueries(Protocol):
    """Lectures pour /api/admin/pipeline/runs/*."""

    def list_runs(self, limit: int = 50) -> list[RunSummary]: ...

    def get_run(self, run_id: int) -> RunDetail | None: ...
