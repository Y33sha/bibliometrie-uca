"""Router admin pipeline-runs : snapshots de runs (observables + métriques).

Expose `/api/admin/pipeline-runs/*` qui sert à la page admin Phase 2.2 du
chantier observabilité. Liste des derniers snapshots + détail par id avec
payload complet (observables, metrics_per_phase, métadonnées).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.ports.api.pipeline_runs_queries import (
    PipelineRunDetail,
    PipelineRunsQueries,
    PipelineRunSummary,
)
from interfaces.api.deps import pipeline_runs_queries_sync

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/pipeline-runs", response_model=list[PipelineRunSummary])
def list_pipeline_runs(
    limit: int = Query(50, ge=1, le=200),
    queries: PipelineRunsQueries = Depends(pipeline_runs_queries_sync),
) -> list[PipelineRunSummary]:
    """N derniers snapshots de runs pipeline (plus récent en premier)."""
    return queries.list_recent(limit=limit)


@router.get("/api/admin/pipeline-runs/{run_id}", response_model=PipelineRunDetail)
def get_pipeline_run(
    run_id: int,
    queries: PipelineRunsQueries = Depends(pipeline_runs_queries_sync),
) -> PipelineRunDetail:
    """Détail d'un run : payload JSONB complet (observables + métriques + métadonnées)."""
    detail = queries.get_by_id(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    return detail
