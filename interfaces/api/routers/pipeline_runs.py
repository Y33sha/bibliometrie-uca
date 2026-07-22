"""Router du pipeline : statut du run en cours, historique des exécutions, logs de phase. Sert `/api/pipeline/*`.

Deux origines pour ces lectures. Le statut du run en cours vient de `logs/status.json`, écrit par l'orchestrateur, et le log d'une phase est découpé de `logs/pipeline.log` par `infrastructure.observability.phase_logs` : ces deux-là ne passent par aucun port, les fichiers étant l'état que l'orchestrateur laisse derrière lui. L'historique des runs, lui, est servi en base par `PipelineRunsQueries` ; il agrège les exécutions de phase par run, et le détail d'un run rend ses phases dans l'ordre, chacune avec son rendement et son écart de durée au médian historique, recalculés à la lecture.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from application.pipeline.phase_order import PHASE_ORDER
from application.ports.api.pipeline_runs_queries import (
    PipelineRunsQueries,
    RunDetail,
    RunSummary,
)
from infrastructure.observability.phase_logs import read_phase_log
from infrastructure.observability.pipeline_status import read_status
from interfaces.api.deps import pipeline_runs_queries
from interfaces.api.models import PipelinePhaseLog, PipelineStatus

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/status", response_model=PipelineStatus | None)
def pipeline_status() -> PipelineStatus | None:
    """Statut du pipeline en cours, ou null si aucun ne tourne.

    Un `status.json` orphelin (PID mort) est traité comme inactif et nettoyé par `read_status`.
    """
    status = read_status()
    return PipelineStatus.model_validate(status) if status else None


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


@router.get("/runs/{run_id}/phases/{phase}/log", response_model=PipelinePhaseLog)
def phase_log(run_id: int, phase: str) -> PipelinePhaseLog:
    """Log d'une phase, découpé depuis `logs/pipeline.log`.

    `available` vaut vrai quand la section de la phase a été retrouvée ; sinon `content` est vide, que le fichier soit absent (`LOG_TO_FILE` inactif) ou que la section ait été purgée.
    """
    content = read_phase_log(run_id, phase)
    if content is None:
        return PipelinePhaseLog(available=False, content="")
    return PipelinePhaseLog(available=True, content=content)
