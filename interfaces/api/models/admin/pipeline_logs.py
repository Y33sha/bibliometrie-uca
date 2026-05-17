"""Modèles Pydantic pour la page admin pipeline (status + logs + reports)."""

from pydantic import BaseModel


class PipelineStatus(BaseModel):
    """État du pipeline en cours (lu depuis logs/status.json)."""

    running: bool
    mode: str
    phase: str
    started_at: str
    phase_started_at: str
    phases_done: int
    phases_total: int


class PipelineLogsResponse(BaseModel):
    content: str


class PipelineReportItem(BaseModel):
    filename: str
    label: str


class PipelineReportContent(BaseModel):
    filename: str
    content: str
