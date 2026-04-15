"""Endpoints pour consulter les rapports et le statut du pipeline."""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter()

BASE = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = BASE / "pipeline" / "reports"
STATUS_FILE = BASE / "pipeline" / "status.json"


@router.get("/api/admin/pipeline/status")
async def pipeline_status():
    """Retourne le statut du pipeline en cours, ou null si aucun ne tourne."""
    if not STATUS_FILE.exists():
        return None
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


CRON_LOG = BASE / "processing" / "logs" / "cron.log"


@router.get("/api/admin/pipeline/logs")
async def pipeline_logs(lines: int = 200):
    """Retourne les N dernières lignes du cron.log."""
    if not CRON_LOG.exists():
        return {"content": ""}
    try:
        text = CRON_LOG.read_text(encoding="utf-8", errors="replace")
        tail = "\n".join(text.splitlines()[-lines:])
        return {"content": tail}
    except OSError:
        return {"content": ""}


@router.get("/api/admin/pipeline/reports")
async def list_reports():
    """Liste les rapports pipeline disponibles (plus récent en premier)."""
    if not REPORTS_DIR.exists():
        return []
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.md"), reverse=True):
        # Extraire date/heure du nom de fichier (YYYY-MM-DD_HHMMSS.md)
        stem = f.stem
        try:
            date_part, time_part = stem.split("_", 1)
            label = f"{date_part} {time_part[:2]}:{time_part[2:4]}"
        except (ValueError, IndexError):
            label = stem
        reports.append({"filename": f.name, "label": label})
    return reports


@router.get("/api/admin/pipeline/reports/{filename}")
async def get_report(filename: str):
    """Retourne le contenu d'un rapport pipeline."""
    # Sécurité : empêcher le path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    filepath = REPORTS_DIR / filename
    if not filepath.exists() or not filepath.suffix == ".md":
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    return {"filename": filename, "content": filepath.read_text(encoding="utf-8")}
