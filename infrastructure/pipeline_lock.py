"""Lock fichier pour empêcher deux pipelines simultanés.

Un seul `run_pipeline.py` peut tourner à la fois sur la base. Sans ça, deux pipelines en parallèle (typiquement cron + lancement manuel) déclenchent des deadlocks Postgres et risquent des états applicatifs incohérents (deux phases personnes qui fusionnent différemment, etc.).

Le lock est un fichier `logs/pipeline.lock` qui contient le PID du process actuel.

- Démarrage : si le fichier existe et le PID dedans est vivant → on abort (sauf `force=True` qui SIGTERM puis SIGKILL le précédent).
- Fin (normale ou exception) : `atexit` supprime le lockfile.
- Lockfile orphelin (crash brutal SIGKILL/OOM) : le PID dedans est mort → on l'écrase silencieusement au démarrage suivant.

Sur Windows, la vivacité passe par `OpenProcess` (`infrastructure.process.is_pid_alive`) et le `--force` envoie `SIGTERM`, que Windows exécute en `TerminateProcess` (arrêt immédiat, sans l'escalade SIGKILL du POSIX).
"""

import atexit
import logging
import os
import signal
import sys
import time
from pathlib import Path

from infrastructure.process import is_pid_alive

log = logging.getLogger(__name__)

PIPELINE_LOCK_FILE = Path(__file__).resolve().parent.parent / "logs" / "pipeline.lock"

_SIGTERM_GRACE_SECONDS = 30


class PipelineAlreadyRunningError(RuntimeError):
    """Levée si un autre pipeline tourne déjà et que --force n'a pas été demandé."""


def _read_lock_pid(lockfile: Path) -> int | None:
    """Lit le PID dans le lockfile. Retourne None si fichier absent ou contenu corrompu."""
    try:
        return int(lockfile.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _terminate_existing(pid: int, *, grace_seconds: int = _SIGTERM_GRACE_SECONDS) -> None:
    """SIGTERM le process précédent, attend grace_seconds, SIGKILL en fallback."""
    log.warning("Pipeline en cours détecté (PID %d) — SIGTERM envoyé", pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        log.info("PID %d déjà terminé entre détection et SIGTERM", pid)
        return
    for _ in range(grace_seconds):
        if not is_pid_alive(pid):
            log.info("Pipeline précédent (PID %d) terminé proprement", pid)
            return
        time.sleep(1)
    if sys.platform == "win32":
        return  # Windows : le SIGTERM ci-dessus a déjà fait un TerminateProcess ; SIGKILL n'existe pas.
    log.warning("Pipeline précédent (PID %d) ne répond pas après %ds — SIGKILL", pid, grace_seconds)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    time.sleep(1)


def acquire_pipeline_lock(*, force: bool = False, lockfile: Path = PIPELINE_LOCK_FILE) -> None:
    """Acquiert le lock pipeline. À appeler en début de `run_pipeline.main()`.

    Lève `PipelineAlreadyRunningError` si un autre pipeline tourne et `force=False`. Avec `force=True`, kill le précédent (SIGTERM puis SIGKILL) et prend le lock.

    Enregistre `release_pipeline_lock` via atexit pour le nettoyage automatique.
    """
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    existing_pid = _read_lock_pid(lockfile)
    if existing_pid is not None and is_pid_alive(existing_pid):
        if force:
            _terminate_existing(existing_pid)
        else:
            raise PipelineAlreadyRunningError(
                f"Pipeline déjà en cours (PID {existing_pid}). Utiliser --force pour le tuer et reprendre."
            )
    # Soit lockfile absent, soit orphelin (PID mort), soit on vient de tuer : on écrase.
    lockfile.write_text(str(os.getpid()))
    atexit.register(release_pipeline_lock, lockfile=lockfile)


def release_pipeline_lock(*, lockfile: Path = PIPELINE_LOCK_FILE) -> None:
    """Supprime le lockfile s'il pointe vers notre PID. Idempotent.

    On vérifie qu'on est bien le owner avant de supprimer : évite de retirer un lock qui aurait été pris par un autre process si on a été kill et qu'un nouveau pipeline a démarré entre temps.
    """
    owner_pid = _read_lock_pid(lockfile)
    if owner_pid == os.getpid():
        try:
            lockfile.unlink()
        except FileNotFoundError:
            pass
