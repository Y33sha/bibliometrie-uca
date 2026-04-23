"""Capture des logs et génération du rapport pipeline."""

import datetime
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS_ROOT = BASE / "logs"
REPORTS_DIR = LOGS_ROOT / "reports"


def _current_reports_dir() -> Path:
    is_sandbox = os.environ.get("BIBLIOMETRIE_SANDBOX") == "1"
    return REPORTS_DIR / "sandbox" if is_sandbox else REPORTS_DIR


def get_last_report_date() -> datetime.date | None:
    """Date (YYYY-MM-DD) du plus récent rapport de pipeline, ou None.

    Les rapports sont nommés `YYYY-MM-DD_HHMMSS.md` (cf. `generate_report`).
    Respecte `BIBLIOMETRIE_SANDBOX` pour viser le bon répertoire.
    """
    reports_dir = _current_reports_dir()
    if not reports_dir.exists():
        return None
    dates = []
    for f in reports_dir.glob("*.md"):
        try:
            dates.append(datetime.date.fromisoformat(f.name[:10]))
        except ValueError:
            continue
    return max(dates) if dates else None


# Fichiers log à exclure de la capture (sortie orchestrateur, loggers parasites)
_EXCLUDED_LOGS = {"cron.log", "zenodo.log"}


def _iter_log_files() -> list[Path]:
    """Retourne tous les fichiers .log sous ``logs/`` (hors reports/ et exclus)."""
    if not LOGS_ROOT.exists():
        return []
    files = []
    for f in LOGS_ROOT.rglob("*.log"):
        if f.name in _EXCLUDED_LOGS:
            continue
        if REPORTS_DIR in f.parents:
            continue
        files.append(f)
    return files


def capture_log_offsets() -> dict[str, int]:
    """Note la taille actuelle de chaque fichier .log.

    Retourne un dict {chemin_absolu: byte_offset} pour pouvoir
    lire uniquement le contenu ajouté après cet instant.
    """
    return {str(f): f.stat().st_size for f in _iter_log_files()}


def read_new_logs(offsets: dict[str, int]) -> str:
    """Lit le contenu ajouté dans les fichiers .log depuis les offsets.

    Retourne le texte concaténé (avec en-têtes par fichier).
    """
    parts = []
    for f in sorted(_iter_log_files()):
        path = str(f)
        prev_size = offsets.get(path, 0)
        current_size = f.stat().st_size
        if current_size <= prev_size:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            fh.seek(prev_size)
            content = fh.read().rstrip()
        if content:
            rel = f.relative_to(BASE)
            parts.append(f"### {rel.as_posix()}\n```\n{content}\n```")
    return "\n\n".join(parts)


def generate_report(
    mode: str,
    sources: set[str],
    phases: list[tuple[str, float, str]],  # [(name, duration_s, logs)]
    total_duration: float,
) -> str:
    """Génère le rapport Markdown et l'écrit dans logs/reports/."""
    now = datetime.datetime.now()
    filename = now.strftime("%Y-%m-%d_%H%M%S") + ".md"
    is_sandbox = os.environ.get("BIBLIOMETRIE_SANDBOX") == "1"

    sandbox_label = " (SANDBOX)" if is_sandbox else ""
    lines = [
        f"# Rapport pipeline{sandbox_label} — {now.strftime('%d/%m/%Y %H:%M')}",
        "",
        f"- **Mode** : {mode}",
        f"- **Sources** : {', '.join(sorted(sources))}",
        f"- **Durée totale** : {total_duration:.0f}s ({total_duration / 60:.1f} min)",
        f"- **Phases** : {len(phases)}",
        "",
    ]

    for phase_name, duration, logs in phases:
        lines.append(f"## {phase_name} ({duration:.1f}s)")
        lines.append("")

        if logs:
            lines.append("<details>")
            lines.append(f"<summary>Logs détaillés — {phase_name}</summary>")
            lines.append("")
            lines.append(logs)
            lines.append("")
            lines.append("</details>")
            lines.append("")

    reports_dir = _current_reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    filepath = reports_dir / filename
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return str(filepath)
