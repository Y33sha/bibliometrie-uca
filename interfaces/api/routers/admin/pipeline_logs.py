"""Router /api/admin/pipeline/status et /api/admin/pipeline/logs/* — ce que le pipeline laisse dans ses fichiers.

Le statut du run en cours vient de `logs/status.json`, écrit par l'orchestrateur ; le log d'une phase est découpé de `logs/pipeline.log` par `infrastructure.observability.phase_logs`. L'historique structuré des runs est servi par le router `pipeline_phase_executions`.
"""

from fastapi import APIRouter

from infrastructure.observability.phase_logs import read_phase_log
from infrastructure.observability.pipeline_status import read_status
from interfaces.api.models import PipelinePhaseLog, PipelineStatus

router = APIRouter()


@router.get("/api/admin/pipeline/status", response_model=PipelineStatus | None)
def pipeline_status() -> PipelineStatus | None:
    """Retourne le statut du pipeline en cours, ou null si aucun ne tourne.

    Un status.json orphelin (PID mort) est traité comme "inactif" et nettoyé par `read_status`.
    """
    status = read_status()
    return PipelineStatus.model_validate(status) if status else None


@router.get(
    "/api/admin/pipeline/runs/{run_id}/phases/{phase}/log",
    response_model=PipelinePhaseLog,
)
def phase_log(run_id: int, phase: str) -> PipelinePhaseLog:
    """Log d'une phase, découpé depuis `logs/pipeline.log`.

    `available` vaut vrai quand la section de la phase a été retrouvée ; sinon `content` est vide, que le fichier soit absent (`LOG_TO_FILE` inactif) ou que la section ait été purgée.
    """
    content = read_phase_log(run_id, phase)
    if content is None:
        return PipelinePhaseLog(available=False, content="")
    return PipelinePhaseLog(available=True, content=content)
