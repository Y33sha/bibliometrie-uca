"""Collecte de métriques pour le rapport pipeline.

Prend des snapshots de la base avant/après chaque phase
et calcule les deltas. Capture les logs détaillés.
Génère un rapport Markdown.
"""

import datetime
from pathlib import Path

from db.connection import get_connection
from utils.sources import ALL_SOURCES

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
            path = str(f)
            prev_size = offsets.get(path, 0)
            current_size = f.stat().st_size
            if current_size <= prev_size:
                continue
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(prev_size)
                content = fh.read().rstrip()
            if content:
                # En-tête relatif au projet
                rel = f.relative_to(BASE)
                parts.append(f"### {rel}\n```\n{content}\n```")
    return "\n\n".join(parts)


def snapshot(conn) -> dict:
    """Prend un snapshot des compteurs de la base."""
    cur = conn.cursor()
    counts = {}

    tables = [
        ("staging_pending", "SELECT COUNT(*) FROM staging WHERE processed = FALSE"),
        ("source_documents", "SELECT COUNT(*) FROM source_documents"),
        ("source_authors", "SELECT COUNT(*) FROM source_authors"),
        ("source_authorships", "SELECT COUNT(*) FROM source_authorships"),
        ("source_authorships_in_perimeter", "SELECT COUNT(*) FROM source_authorships WHERE in_perimeter = TRUE"),
        ("source_authorships_with_person", "SELECT COUNT(*) FROM source_authorships WHERE person_id IS NOT NULL"),
        ("publications", "SELECT COUNT(*) FROM publications"),
        ("authorships", "SELECT COUNT(*) FROM authorships"),
        ("persons", "SELECT COUNT(*) FROM persons WHERE rejected = FALSE"),
        ("person_name_forms", "SELECT COUNT(*) FROM person_name_forms"),
        ("person_identifiers", "SELECT COUNT(*) FROM person_identifiers"),
        ("addresses", "SELECT COUNT(*) FROM addresses"),
        ("addresses_with_countries", "SELECT COUNT(*) FROM addresses WHERE countries IS NOT NULL"),
        ("sd_with_countries", "SELECT COUNT(*) FROM source_documents WHERE countries IS NOT NULL"),
        ("publications_with_countries", "SELECT COUNT(*) FROM publications WHERE countries IS NOT NULL"),
    ]
    for name, query in tables:
        try:
            cur.execute(query)
            counts[name] = cur.fetchone()[0]
        except Exception:
            counts[name] = 0

    # Compteurs par source
    for source in ALL_SOURCES:
        cur.execute("SELECT COUNT(*) FROM source_documents WHERE source = %s", (source,))
        counts[f"sd_{source}"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM staging WHERE source = %s AND processed = FALSE", (source,))
        counts[f"staging_{source}"] = cur.fetchone()[0]

    cur.close()
    return counts


def compute_deltas(before: dict, after: dict) -> dict:
    """Calcule les différences entre deux snapshots."""
    deltas = {}
    for key in after:
        b = before.get(key, 0)
        a = after[key]
        if a != b:
            deltas[key] = {"before": b, "after": a, "delta": a - b}
    return deltas


def _fmt_delta(d: int) -> str:
    if d > 0:
        return f"+{d}"
    return str(d)


def generate_report(
    mode: str,
    sources: set[str],
    phases: list[tuple[str, float, dict, str]],  # [(name, duration_s, deltas, logs)]
    total_duration: float,
) -> str:
    """Génère le rapport Markdown et l'écrit dans pipeline/reports/."""
    now = datetime.datetime.now()
    filename = now.strftime("%Y-%m-%d_%H%M%S") + ".md"

    lines = [
        f"# Rapport pipeline — {now.strftime('%d/%m/%Y %H:%M')}",
        "",
        f"- **Mode** : {mode}",
        f"- **Sources** : {', '.join(sorted(sources))}",
        f"- **Durée totale** : {total_duration:.0f}s ({total_duration/60:.1f} min)",
        f"- **Phases** : {len(phases)}",
        "",
    ]

    for phase_name, duration, deltas, logs in phases:
        lines.append(f"## {phase_name} ({duration:.1f}s)")
        lines.append("")
        if not deltas:
            lines.append("Aucun changement détecté.")
        else:
            lines.append("| Indicateur | Avant | Après | Delta |")
            lines.append("|---|---:|---:|---:|")
            for key, vals in sorted(deltas.items()):
                label = key.replace("_", " ").replace("sd ", "docs ").replace("staging ", "staging ")
                lines.append(f"| {label} | {vals['before']} | {vals['after']} | {_fmt_delta(vals['delta'])} |")
        lines.append("")

        if logs:
            lines.append("<details>")
            lines.append(f"<summary>Logs détaillés — {phase_name}</summary>")
            lines.append("")
            lines.append(logs)
            lines.append("")
            lines.append("</details>")
            lines.append("")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = REPORTS_DIR / filename
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return str(filepath)
