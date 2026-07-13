"""Configuration centralisée du logging.

Par défaut, les logs sont émis au format JSON (une ligne = un record) pour permettre leur agrégation par un collecteur externe (Loki, ELK, stdout→fluentd). Pour le format texte lisible en dev : `export LOG_FORMAT=text`.

Tous les fichiers .log sont consolidés sous `PROJECT_ROOT/logs/`, en reproduisant l'arborescence du caller (voir `_rebase_log_dir`).
"""

import contextvars
import io
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from infrastructure import PROJECT_ROOT as _PROJECT_ROOT

# Phase pipeline courante, injectée comme nom de logger dans chaque record émis pendant la phase (voir `_PhaseNameFilter`).
# Posée par l'orchestrateur (`run_pipeline`) ; jamais renseignée hors run pipeline (API, scripts CLI).
_log_phase: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "pipeline_log_phase", default=None
)


def set_log_phase(phase: str | None) -> contextvars.Token[str | None]:
    """Définit la phase pipeline courante. Retourne un token à passer à `reset_log_phase` pour restaurer la valeur précédente."""
    return _log_phase.set(phase)


def reset_log_phase(token: contextvars.Token[str | None]) -> None:
    """Restaure la phase pipeline précédant `set_log_phase`."""
    _log_phase.reset(token)


class _PhaseNameFilter(logging.Filter):
    """Réécrit `record.name` avec la phase pipeline courante quand elle est posée.

    Rend chaque ligne auto-située : `record.name` porte le nom de la phase (`normalize:`, `subjects:`…). Sans phase active (API, scripts), le nom du logger d'origine est conservé.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        phase = _log_phase.get()
        if phase:
            record.name = phase
        return True


# Attributs internes de logging.LogRecord à ne PAS inclure dans la sortie JSON (déjà couverts, ou trop verbeux).
_STD_RECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Formatter produisant une ligne JSON par record.

    Champs : timestamp (ISO UTC), level, logger, message. Les `extra={...}` passés au logger sont fusionnés à la racine ; les exceptions (`exc_info`) sont formatées dans `exception`.
    """

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        # Fusionne les champs `extra={...}` passés au logger
        extras = {k: v for k, v in record.__dict__.items() if k not in _STD_RECORD_ATTRS}
        data.update(extras)
        return json.dumps(data, default=str, ensure_ascii=False)


def _make_formatter() -> logging.Formatter:
    """Retourne le formatter selon LOG_FORMAT (json par défaut, text en fallback)."""
    fmt = os.environ.get("LOG_FORMAT", "json").lower()
    if fmt == "text":
        return logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    return JsonFormatter()


def _rebase_log_dir(log_dir: str) -> Path:
    """Rebase `log_dir` vers `PROJECT_ROOT/logs/<relpath>/`.

    Le relpath est calculé à partir du chemin du caller relatif à la racine du projet. Un suffixe `logs` final est éliminé pour éviter une imbrication redondante `logs/.../logs/`. Un chemin hors projet est replié sous `PROJECT_ROOT/logs/` en préservant ses segments nommés.
    """
    p = Path(log_dir)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    try:
        rel = p.resolve().relative_to(_PROJECT_ROOT)
    except ValueError:
        rel = Path(*p.resolve().parts[1:])
    parts = list(rel.parts)
    while parts and parts[-1] == "logs":
        parts.pop()
    return _PROJECT_ROOT / "logs" / Path(*parts) if parts else _PROJECT_ROOT / "logs"


def setup_logger(name: str, log_dir: str) -> logging.Logger:
    """Configure un logger avec sortie console, et fichier optionnel.

    Le FileHandler est **opt-in** via `LOG_TO_FILE=true` : par défaut l'app n'écrit pas sur disque (logs sur stdout, 12-factor). Activer en dev local pour garder un historique.

    Quand activé, le `log_dir` passé par le caller est rebasé vers `PROJECT_ROOT/logs/<relpath>/` (voir `_rebase_log_dir`), regroupant tous les fichiers `.log` sous une arborescence unique. Crée le répertoire si nécessaire.

    Configure uniquement le logger nommé (pas le root logger). Format : JSON par défaut, texte si LOG_FORMAT=text.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Éviter les doublons si le logger est configuré plusieurs fois
    if logger.handlers:
        return logger

    fmt = _make_formatter()

    # Force UTF-8 sur la console pour éviter les UnicodeEncodeError Windows (cp1252)
    # On enveloppe stdout.buffer sans se l'approprier (line_buffering pour flush immédiat)
    utf8_stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    utf8_stream.close = lambda: None  # type: ignore[method-assign]  # Empêcher la fermeture de stdout.buffer
    console = logging.StreamHandler(stream=utf8_stream)
    console.setFormatter(fmt)
    console.addFilter(_PhaseNameFilter())
    logger.addHandler(console)

    if os.environ.get("LOG_TO_FILE", "").lower() == "true":
        target_dir = _rebase_log_dir(log_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(target_dir / f"{name}.log"), encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.addFilter(_PhaseNameFilter())
        logger.addHandler(file_handler)

    return logger


def configure_root_logging(level: int = logging.INFO) -> None:
    """Configure le root logger (utilisé par les modules qui font simplement `logging.getLogger(__name__)` sans passer par setup_logger, notamment les routers FastAPI).

    Appelé au démarrage de backend/app.py.
    """
    root = logging.getLogger()
    root.setLevel(level)
    # Nettoyer les handlers par défaut (uvicorn peut en ajouter après)
    for h in list(root.handlers):
        root.removeHandler(h)
    # Sous pytest, ne pas attacher de StreamHandler : pytest pose son
    # propre LogCaptureHandler (accessible via la fixture `caplog` et
    # affiché automatiquement sur échec). Attacher un handler stdout en
    # plus duplique les records et pollue la sortie des tests.
    if os.environ.get("PYTEST_VERSION") or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_make_formatter())
    handler.addFilter(_PhaseNameFilter())
    root.addHandler(handler)
