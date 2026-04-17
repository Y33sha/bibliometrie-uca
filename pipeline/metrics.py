"""Capture des logs et génération du rapport pipeline."""

import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
REPORTS_DIR = Path(__file__).parent / "reports"

LOG_DIRS = [
    BASE / "processing" / "logs",
    BASE / "extraction" / "hal" / "logs",
    BASE / "extraction" / "openalex" / "logs",
    BASE / "extraction" / "wos" / "logs",
    BASE / "extraction" / "scanr" / "logs",
    BASE / "extraction" / "theses" / "logs",
]


# Fichiers log à exclure de la capture (sortie orchestrateur, loggers parasites)
_EXCLUDED_LOGS = {"cron.log", "zenodo.log"}


def capture_log_offsets() -> dict[str, int]:
    """Note la taille actuelle de chaque fichier .log.

    Retourne un dict {chemin_absolu: byte_offset} pour pouvoir
    lire uniquement le contenu ajouté après cet instant.
    """
    offsets = {}
    for log_dir in LOG_DIRS:
        if not log_dir.exists():
            continue
        for f in log_dir.glob("*.log"):
            if f.name in _EXCLUDED_LOGS:
                continue
            offsets[str(f)] = f.stat().st_size
    return offsets


def read_new_logs(offsets: dict[str, int]) -> str:
    """Lit le contenu ajouté dans les fichiers .log depuis les offsets.

    Retourne le texte concaténé (avec en-têtes par fichier).
    """
    parts = []
    for log_dir in LOG_DIRS:
        if not log_dir.exists():
            continue
        for f in sorted(log_dir.glob("*.log")):
            if f.name in _EXCLUDED_LOGS:
                continue
            path = str(f)
            prev_size = offsets.get(path, 0)
            current_size = f.stat().st_size
            if current_size <= prev_size:
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                fh.seek(prev_size)
                content = fh.read().rstrip()
            if content:
                # En-tête relatif au projet
                rel = f.relative_to(BASE)
                parts.append(f"### {rel}\n```\n{content}\n```")
    return "\n\n".join(parts)


def generate_report(
    mode: str,
    sources: set[str],
    phases: list[tuple[str, float, str]],  # [(name, duration_s, logs)]
    total_duration: float,
) -> str:
    """Génère le rapport Markdown et l'écrit dans pipeline/reports/."""
    import os

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

    reports_dir = REPORTS_DIR / "sandbox" if is_sandbox else REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    filepath = reports_dir / filename
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return str(filepath)
