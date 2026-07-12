"""Router admin : exécutions de phase du pipeline (observabilité par phase).

Expose `/api/admin/pipeline/runs` (liste agrégée par run) et
`/api/admin/pipeline/runs/{run_id}` (détail : phases avec rendement et écart de
durée recalculés à la lecture).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from application.pipeline.phase_order import PHASE_ORDER
from application.ports.api.pipeline_phase_executions_queries import (
    PhaseExecutionsQueries,
    RunDetail,
    RunSummary,
)
from interfaces.api.deps import pipeline_phase_executions_queries_sync

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/admin/pipeline/phases", response_model=list[str])
def list_phases() -> list[str]:
    """Ordre canonique des phases du pipeline (graphe), pour la trame du ruban."""
    return list(PHASE_ORDER)


@router.get("/api/admin/pipeline/runs", response_model=list[RunSummary])
def list_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    queries: PhaseExecutionsQueries = Depends(pipeline_phase_executions_queries_sync),
) -> list[RunSummary]:
    """Fenêtre de runs (agrégés par `run_id`), plus récent en premier ; `offset` pour
    le chargement incrémental."""
    return queries.list_runs(limit=limit, offset=offset)


@router.get("/api/admin/pipeline/runs/{run_id}", response_model=RunDetail)
def get_run(
    run_id: int,
    queries: PhaseExecutionsQueries = Depends(pipeline_phase_executions_queries_sync),
) -> RunDetail:
    """Détail d'un run : ses exécutions de phase avec rendement et écart de durée."""
    detail = queries.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    return detail
