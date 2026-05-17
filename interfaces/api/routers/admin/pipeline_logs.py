"""Endpoints pour consulter les rapports et le statut du pipeline."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from infrastructure.pipeline_status import read_status
from interfaces.api.models import (
    PipelineLogsResponse,
    PipelineReportContent,
    PipelineReportItem,
    PipelineStatus,
)

router = APIRouter()
logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent.parent.parent.parent.parent
REPORTS_DIR = BASE / "logs" / "reports"


@router.get("/api/admin/pipeline/status", response_model=PipelineStatus | None)
def pipeline_status() -> PipelineStatus | None:
    """Retourne le statut du pipeline en cours, ou null si aucun ne tourne.

    Un status.json orphelin (PID mort) est traité comme "inactif" et nettoyé par ``read_status``.
    """
    status = read_status()
    return PipelineStatus.model_validate(status) if status else None


CRON_LOG = BASE / "logs" / "cron.log"


@router.get("/api/admin/pipeline/logs", response_model=PipelineLogsResponse)
def pipeline_logs(lines: int = 200) -> PipelineLogsResponse:
    """Retourne les N dernières lignes du cron.log."""
    if not CRON_LOG.exists():
        return PipelineLogsResponse(content="")
    try:
        text = CRON_LOG.read_text(encoding="utf-8", errors="replace")
        tail = "\n".join(text.splitlines()[-lines:])
        return PipelineLogsResponse(content=tail)
    except OSError:
        return PipelineLogsResponse(content="")


@router.get("/api/admin/pipeline/reports", response_model=list[PipelineReportItem])
def list_reports() -> list[PipelineReportItem]:
    """Liste les rapports pipeline disponibles (plus récent en premier)."""
    if not REPORTS_DIR.exists():
        return []
    reports: list[PipelineReportItem] = []
    for f in sorted(REPORTS_DIR.glob("*.md"), reverse=True):
        # Extraire date/heure du nom de fichier (YYYY-MM-DD_HHMMSS.md)
        stem = f.stem
        try:
            date_part, time_part = stem.split("_", 1)
            label = f"{date_part} {time_part[:2]}:{time_part[2:4]}"
        except (ValueError, IndexError):
            label = stem
        reports.append(PipelineReportItem(filename=f.name, label=label))
    return reports


@router.get("/api/admin/pipeline/reports/{filename}", response_model=PipelineReportContent)
def get_report(filename: str) -> PipelineReportContent:
    """Retourne le contenu d'un rapport pipeline."""
    # Sécurité : empêcher le path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    filepath = REPORTS_DIR / filename
    if not filepath.exists() or not filepath.suffix == ".md":
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    return PipelineReportContent(filename=filename, content=filepath.read_text(encoding="utf-8"))
