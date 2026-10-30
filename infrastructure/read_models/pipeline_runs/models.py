"""Modèles de réponse : lectures sur les exécutions de phase du pipeline (/api/pipeline/runs/*).

La liste regroupe les exécutions par `run_id` ; le statut d'un run est le pire de ses phases. Le détail d'un run renvoie ses phases dans l'ordre d'exécution, chacune avec son écart de durée à la médiane historique, recalculé à la lecture.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from domain.pipeline_runs import PhaseMetricsPayload, PhaseStatus, Signal


class PhaseBrief(BaseModel):
    """Statut d'une phase au sein d'un run, pour le ruban de la liste."""

    phase: str
    status: PhaseStatus


class RunSummary(BaseModel):
    """Ligne de la liste des runs : exécutions d'un même `run_id` regroupées."""

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
    """Exécution de phase, avec les valeurs recalculées à la lecture."""

    phase: str
    started_at: datetime
    ended_at: datetime
    status: PhaseStatus
    duration_s: float
    metrics: PhaseMetricsPayload
    details: dict[str, Any]
    historical_median_duration_s: float | None
    duration_ratio: float | None
    signals: list[Signal]


class RunDetail(BaseModel):
    """Détail d'un run : ses phases et ses totaux."""

    run_id: int
    started_at: datetime
    ended_at: datetime
    mode: str
    sources: list[str]
    status: PhaseStatus
    total_duration_s: float
    phases: list[PhaseExecutionDetail]
