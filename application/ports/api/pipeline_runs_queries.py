"""Port : lectures sur les snapshots de runs pipeline (consommé par /api/admin/pipeline-runs/*).

Sert la liste des derniers runs (résumé) et le détail d'un run (payload complet :
observables + métriques par phase + métadonnées).

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier
`CODE_typage-projections-strict` Phase 4.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from application.ports.pipeline.runs import RunSnapshotPayload


class PipelineRunSummary(BaseModel):
    """Une ligne dans la liste des derniers runs."""

    id: int
    ran_at: datetime
    mode: str
    total_duration_s: float
    sources: list[str]
    phases_run: list[str]


class PipelineRunDetail(BaseModel):
    """Détail complet d'un run."""

    id: int
    ran_at: datetime
    mode: str
    payload: RunSnapshotPayload


class PipelineRunsQueries(Protocol):
    """Lectures pour /api/admin/pipeline-runs/*."""

    def list_recent(self, limit: int = 50) -> list[PipelineRunSummary]: ...

    def get_by_id(self, run_id: int) -> PipelineRunDetail | None: ...
