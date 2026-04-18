"""Configuration centralisée du logging.

Par défaut, les logs sont émis au format JSON (une ligne = un record) pour
permettre leur agrégation par un collecteur externe (Loki, ELK, stdout→fluentd).
Pour revenir au format texte lisible en dev : `export LOG_FORMAT=text`.
"""

import io
import json
import logging
import os
import sys
from datetime import datetime, timezone

# Attributs internes de logging.LogRecord à ne PAS inclure dans la sortie JSON
# (ils sont soit déjà couverts, soit trop verbeux).
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

    Champs : timestamp (ISO UTC), level, logger, message.
    Les `extra={...}` passés au logger sont fusionnés à la racine.
    Les exceptions (`exc_info`) sont formatées dans `exception`.
    """

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
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


def setup_logger(name: str, log_dir: str) -> logging.Logger:
    """Configure un logger avec sortie console + fichier.

    Crée le répertoire de logs si nécessaire.
    Configure uniquement le logger nommé (pas le root logger).
    Format : JSON par défaut, texte si LOG_FORMAT=text.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{name}.log")

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Éviter les doublons si le logger est configuré plusieurs fois
    if logger.handlers:
        return logger

    fmt = _make_formatter()

    # Force UTF-8 sur la console pour éviter les UnicodeEncodeError Windows (cp1252)
    # On wrape stdout.buffer sans en prendre ownership (line_buffering pour flush immédiat)
    utf8_stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    utf8_stream.close = lambda: None  # Empêcher la fermeture de stdout.buffer
    console = logging.StreamHandler(stream=utf8_stream)
    console.setFormatter(fmt)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)

    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger


def configure_root_logging(level: int = logging.INFO) -> None:
    """Configure le root logger (utilisé par les modules qui font simplement
    `logging.getLogger(__name__)` sans passer par setup_logger, notamment
    les routers FastAPI).

    Appelé au démarrage de backend/app.py.
    """
    root = logging.getLogger()
    root.setLevel(level)
    # Nettoyer les handlers par défaut (uvicorn peut en ajouter après)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_make_formatter())
    root.addHandler(handler)
