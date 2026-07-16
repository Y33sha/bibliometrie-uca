"""Router /api/admin/pipeline/runs/* — l'historique des exécutions du pipeline.

La liste agrège les exécutions de phase par run. Le détail d'un run rend ses phases dans l'ordre, chacune avec son rendement et son écart de durée au médian historique, recalculés à la lecture.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from application.pipeline.phase_order import PHASE_ORDER
from application.ports.api.pipeline_phase_executions_queries import (
    PhaseExecutionsQueries,
    RunDetail,
    RunSummary,
)
from interfaces.api.deps import pipeline_phase_executions_queries

router = APIRouter()


@router.get("/api/admin/pipeline/phases", response_model=list[str])
def list_phases() -> list[str]:
    """Ordre canonique des phases du pipeline (graphe), pour la trame du ruban."""
    return list(PHASE_ORDER)


@router.get("/api/admin/pipeline/runs", response_model=list[RunSummary])
def list_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    queries: PhaseExecutionsQueries = Depends(pipeline_phase_executions_queries),
) -> list[RunSummary]:
    """Fenêtre de runs agrégés par `run_id`, le plus récent en tête ; `offset` sert au chargement incrémental."""
    return queries.list_runs(limit=limit, offset=offset)


@router.get("/api/admin/pipeline/runs/{run_id}", response_model=RunDetail)
def get_run(
    run_id: int,
    queries: PhaseExecutionsQueries = Depends(pipeline_phase_executions_queries),
) -> RunDetail:
    """Détail d'un run : ses exécutions de phase avec rendement et écart de durée."""
    detail = queries.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    return detail
