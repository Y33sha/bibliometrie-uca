"""Router du pipeline : historique des exécutions. Sert `/api/pipeline/*`.

L'historique des runs est servi en base par `PipelineRunsQueries` : il agrège les exécutions de phase par run, et le détail d'un run rend ses phases dans l'ordre, chacune avec son rendement et son écart de durée au médian historique, recalculés à la lecture. Un échec ou un avertissement y figure sous forme de signal, avec son code et son message.

La trace brute d'une exécution vit dans le flux de sortie standard de l'orchestrateur, que le collecteur de l'hébergement recueille.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from application.pipeline.phase_order import PHASE_ORDER
from application.ports.read_models.pipeline_runs_queries import (
    PipelineRunsQueries,
    RunDetail,
    RunSummary,
)
from interfaces.api.deps import pipeline_runs_queries

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/phases", response_model=list[str])
def list_phases() -> list[str]:
    """Ordre canonique des phases du pipeline (graphe), pour la trame du ruban."""
    return list(PHASE_ORDER)


@router.get("/runs", response_model=list[RunSummary])
def list_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    queries: PipelineRunsQueries = Depends(pipeline_runs_queries),
) -> list[RunSummary]:
    """Fenêtre de runs agrégés par `run_id`, le plus récent en tête ; `offset` sert au chargement incrémental."""
    return queries.list_runs(limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(
    run_id: int,
    queries: PipelineRunsQueries = Depends(pipeline_runs_queries),
) -> RunDetail:
    """Détail d'un run : ses exécutions de phase avec rendement et écart de durée."""
    detail = queries.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    return detail
