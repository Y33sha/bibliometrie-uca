"""Port : lectures sur les exécutions de phase du pipeline (/api/pipeline/runs/*).

La liste agrège les exécutions par `run_id` (statut global = le pire des statuts de
phase). Le détail d'un run renvoie ses phases dans l'ordre d'exécution, chacune avec
son écart de durée au médian historique, recalculé à la lecture par l'adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from application.ports.pipeline.phase_executions import (
    PhaseMetricsPayload,
    PhaseStatus,
    Signal,
)


class PhaseBrief(BaseModel):
    """Statut d'une phase au sein d'un run, pour le ruban de la liste."""

    phase: str
    status: PhaseStatus


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
    phases: list[PhaseBrief]


class PhaseExecutionDetail(BaseModel):
    """Une exécution de phase, enrichie des valeurs recalculées à la lecture."""

    phase: str
    started_at: datetime
    ended_at: datetime
    status: PhaseStatus
    duration_s: float
    metrics: PhaseMetricsPayload
    details: dict[str, object]
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


class PipelineRunsQueries(Protocol):
    """Lectures pour /api/pipeline/runs/*."""

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[RunSummary]: ...

    def get_run(self, run_id: int) -> RunDetail | None: ...
