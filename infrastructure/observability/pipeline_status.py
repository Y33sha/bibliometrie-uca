"""État du pipeline en cours, persisté dans `logs/status.json`.

Écriture côté orchestrateur (`run_pipeline.py`), lecture côté API (`interfaces/api/routers/admin/pipeline_logs.py`). Le PID du writer est embarqué dans le fichier : si le process est mort (SIGKILL, crash C-level, OOM killer — cas non couverts par atexit/signal), le statut est considéré comme orphelin et nettoyé.
"""

import datetime
import json
import logging
import os

from domain.types import JsonValue
from infrastructure import PROJECT_ROOT
from infrastructure.process import is_pid_alive

log = logging.getLogger(__name__)

STATUS_FILE = PROJECT_ROOT / "logs" / "status.json"


def write_status(
    *,
    mode: str,
    phase: str,
    started_at: str,
    phases_done: int,
    phases_total: int,
) -> None:
    """Écrit le statut courant (avec PID) pour le suivi en temps réel."""
    STATUS_FILE.write_text(
        json.dumps(
            {
                "mode": mode,
                "phase": phase,
                "started_at": started_at,
                "phase_started_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "phases_done": phases_done,
                "phases_total": phases_total,
                "pid": os.getpid(),
            }
        ),
        encoding="utf-8",
    )


def clear_status() -> None:
    """Supprime le fichier de statut."""
    STATUS_FILE.unlink(missing_ok=True)


def read_status() -> dict[str, JsonValue] | None:
    """Lit le statut, ou `None` si aucun pipeline n'est actif.

    Un statut dont le PID est mort est traité comme "pas de pipeline actif" et le fichier est nettoyé au passage (warning loggé).
    """
    if not STATUS_FILE.exists():
        return None
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    pid = data.get("pid")
    if pid is not None and not is_pid_alive(int(pid)):
        log.warning("status.json orphelin (PID %s mort) — nettoyage", pid)
        clear_status()
        return None
    return data
