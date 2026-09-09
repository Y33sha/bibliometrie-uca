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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from infrastructure import PROJECT_ROOT as _PROJECT_ROOT

EcrivainConsole = Callable[[str, TextIO], None]
"""Écrit une ligne de console sur le flux donné, en préservant ce qui s'y affiche déjà."""

_ecrivain_console: EcrivainConsole | None = None


def set_console_writer(ecrire: EcrivainConsole | None) -> None:
    """Détourne l'écriture des lignes de console vers `ecrire`.

    Sert au pipeline, dont les barres de progression occupent le bas du terminal : une écriture directe s'y insère au milieu. Posé par le composition root, l'écrivain vaut pour tous les loggers configurés par ce module.
    """
    global _ecrivain_console
    _ecrivain_console = ecrire


class _FluxConsole(io.TextIOBase):
    """Flux de console dont l'écriture passe par l'écrivain courant."""

    def __init__(self, flux: TextIO) -> None:
        self._flux = flux

    def write(self, texte: str) -> int:
        ligne = texte.rstrip("\n")
        if _ecrivain_console is not None and ligne:
            _ecrivain_console(ligne, self._flux)
            return len(texte)
        return self._flux.write(texte)

    def flush(self) -> None:
        self._flux.flush()

    def isatty(self) -> bool:
        return self._flux.isatty()


_console: TextIO | None = None


def console_stream() -> TextIO:
    """Flux de console, partagé par les loggers et par ce qui s'affiche à côté d'eux.

    Un flux unique permet aux barres de progression et aux lignes de journal de s'effacer mutuellement : deux enveloppes du même descripteur s'ignoreraient.

    L'enveloppe UTF-8 écarte les `UnicodeEncodeError` d'une console cp1252. `line_buffering` vide le tampon à chaque ligne. La fermeture est neutralisée : le tampon de la sortie standard appartient au processus.
    """
    global _console
    if _console is None:
        flux = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
        flux.close = lambda: None  # type: ignore[method-assign]
        _console = flux
    return _console


# Marqueurs délimitant runs et phases dans le flux de log, émis par `run_pipeline` : ils situent une ligne dans son run et sa phase pour qui lit le flux.
RUN_MARKER = "Run pipeline #"
PHASE_MARKER = "PHASE : "
RUN_END_MARKER = "PIPELINE TERMINÉ"

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

    Champs : timestamp (ISO UTC), level, logger, message, et `template` quand le message est formaté à l'émission. Le gabarit reste identique d'une occurrence à l'autre là où le message porte les valeurs du moment : un collecteur y regroupe les lignes d'un même événement, les compte et les surveille sans lire le texte. Les `extra={...}` passés au logger sont fusionnés à la racine ; les exceptions (`exc_info`) sont formatées dans `exception`.
    """

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.args:
            data["template"] = str(record.msg)
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

    Quand activé, le `log_dir` passé par le caller est rebasé vers `PROJECT_ROOT/logs/<relpath>/` (voir `_rebase_log_dir`), regroupant tous les fichiers `.log` sous une arborescence unique. Crée le répertoire si nécessaire, et se rabat sur la seule sortie standard si le disque le refuse (voir `_attach_file_handler`).

    Configure uniquement le logger nommé (pas le root logger). Format : JSON par défaut, texte si LOG_FORMAT=text.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Éviter les doublons si le logger est configuré plusieurs fois
    if logger.handlers:
        return logger

    fmt = _make_formatter()

    console = logging.StreamHandler(stream=_FluxConsole(console_stream()))
    console.setFormatter(fmt)
    console.addFilter(_PhaseNameFilter())
    logger.addHandler(console)

    if os.environ.get("LOG_TO_FILE", "").lower() == "true":
        _attach_file_handler(logger, name, log_dir, fmt)

    return logger


def _attach_file_handler(
    logger: logging.Logger, name: str, log_dir: str, fmt: logging.Formatter
) -> None:
    """Ajoute au logger un fichier sous `PROJECT_ROOT/logs/`, ou s'en passe si le disque le refuse.

    Un système de fichiers en lecture seule — le conteneur de production est cloisonné ainsi — ou un répertoire fermé en écriture rend le fichier impossible. La journalisation retombe alors sur la seule sortie standard, que le runtime collecte de toute façon, et un avertissement dit ce qui manque : une destination de logs indisponible n'est pas une raison d'empêcher l'application de démarrer.
    """
    target_dir = _rebase_log_dir(log_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(target_dir / f"{name}.log"), encoding="utf-8")
    except OSError as e:
        logger.warning(
            "LOG_TO_FILE est demandé mais %s n'est pas accessible en écriture (%s) : "
            "journalisation sur la sortie standard seule.",
            target_dir,
            e,
        )
        return
    file_handler.setFormatter(fmt)
    file_handler.addFilter(_PhaseNameFilter())
    logger.addHandler(file_handler)


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
