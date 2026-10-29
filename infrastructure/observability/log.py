"""Configuration du logging.

Les logs sortent en JSON, une ligne par record, pour un collecteur externe (Loki, ELK, fluentd). `LOG_FORMAT=text` donne le format texte, lisible en développement.

Les fichiers `.log` se rangent sous `PROJECT_ROOT/logs/`, dans l'arborescence de l'appelant (`_rebase_log_dir`).

Une ligne émise avec `extra={"detail": True}` rapporte le cas d'une donnée : le terminal la masque, le journal la garde (`_FiltreDetail`).
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
        flux.close = lambda: None
        _console = flux
    return _console


# Marqueurs délimitant runs et phases dans le flux de log, émis par `run_pipeline` : ils situent une ligne dans son run et sa phase pour qui lit le flux.
RUN_MARKER = "Run pipeline #"
PHASE_MARKER = "PHASE : "
RUN_END_MARKER = "PIPELINE TERMINÉ"

# Phase du pipeline en cours, qui devient le nom du logger de chaque record émis pendant la phase (`_PhaseNameFilter`).
# L'orchestrateur la pose ; hors run (API, scripts), elle reste vide.
_log_phase: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "pipeline_log_phase", default=None
)


def set_log_phase(phase: str | None) -> contextvars.Token[str | None]:
    """Pose la phase du pipeline en cours, et rend le jeton qui restaure la précédente (`reset_log_phase`)."""
    return _log_phase.set(phase)


def reset_log_phase(token: contextvars.Token[str | None]) -> None:
    """Restaure la phase du pipeline d'avant `set_log_phase`."""
    _log_phase.reset(token)


class _PhaseNameFilter(logging.Filter):
    """Écrit la phase du pipeline en cours dans `record.name` : chaque ligne dit sa phase (`normalize:`, `subjects:`…). Sans phase (API, scripts), le nom du logger d'origine reste."""

    def filter(self, record: logging.LogRecord) -> bool:
        phase = _log_phase.get()
        if phase:
            record.name = phase
        return True


# Attributs internes de `LogRecord` exclus de la sortie JSON : déjà repris, ou trop bavards.
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

    Champs : timestamp (ISO UTC), level, logger, message, et `template` quand le message est formaté à l'émission. Le gabarit reste identique d'une occurrence à l'autre là où le message contient les valeurs du moment : un collecteur y regroupe les lignes d'un même événement, les compte et les surveille sans lire le texte. Les `extra={...}` passés au logger sont fusionnés à la racine ; les exceptions (`exc_info`) sont formatées dans `exception`.
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


class _FormatTexte(logging.Formatter):
    """Formatter texte, un record par ligne.

    Les retours chariot et sauts de ligne du message sont échappés : une valeur journalisée, venue d'une requête par exemple, ne peut pas forger une ligne de journal. La trace d'une exception, ajoutée après le message, garde ses lignes.
    """

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802 — nom imposé par logging
        return super().formatMessage(record).replace("\r", "\\r").replace("\n", "\\n")


def _make_formatter() -> logging.Formatter:
    """Formatter choisi par `LOG_FORMAT` : JSON par défaut, texte sur demande."""
    fmt = os.environ.get("LOG_FORMAT", "json").lower()
    if fmt == "text":
        return _FormatTexte("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    return JsonFormatter()


class _FormatConsole(_FormatTexte):
    """Message seul, précédé du niveau à partir de l'avertissement.

    Le titre ouvrant chaque phase situe les lignes qui suivent, et le niveau de l'information vaut pour la quasi-totalité d'entre elles.
    """

    def __init__(self) -> None:
        super().__init__("%(message)s")

    def format(self, record: logging.LogRecord) -> str:
        ligne = super().format(record)
        if record.levelno > logging.INFO:
            return f"[{record.levelname}] {ligne}"
        return ligne


def _console_lisible() -> bool:
    """La console s'adresse à quelqu'un qui la lit : format texte et terminal."""
    return os.environ.get("LOG_FORMAT", "json").lower() == "text" and sys.stdout.isatty()


def _make_console_formatter() -> logging.Formatter:
    """Formatter des lignes de console.

    Devant un terminal, le format texte se réduit au message. Une sortie redirigée ou capturée ajoute l'horodatage, le niveau et la phase.
    """
    if _console_lisible():
        return _FormatConsole()
    return _make_formatter()


class _FiltreDetail(logging.Filter):
    """Écarte les lignes de détail, émises avec `extra={"detail": True}`.

    Une telle ligne rapporte le cas d'une donnée parmi des milliers, par exemple un identifiant écarté à l'écriture. Elle vaut pour qui relit le journal, et encombre le terminal pendant un run.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "detail", False)


def _add_console_filters(handler: logging.Handler) -> None:
    handler.addFilter(_PhaseNameFilter())
    if _console_lisible():
        handler.addFilter(_FiltreDetail())


def _rebase_log_dir(log_dir: str) -> Path:
    """Répertoire `PROJECT_ROOT/logs/<chemin relatif>/` de `log_dir`.

    Le chemin relatif part de la racine du projet. Un `logs` final est retiré, pour éviter `logs/.../logs/`. Un chemin hors projet se range sous `PROJECT_ROOT/logs/`, avec ses segments nommés.
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
    """Configure un logger nommé, avec une sortie console et, sur demande, un fichier.

    Le fichier s'active par `LOG_TO_FILE=true` ; sans lui, l'application écrit seulement sur la sortie standard. Le répertoire passé se range sous `PROJECT_ROOT/logs/` (`_rebase_log_dir`), créé au besoin. Un disque qui refuse l'écriture laisse la seule sortie standard (`_attach_file_handler`). Format JSON par défaut, texte avec `LOG_FORMAT=text`.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    # Le logger a ses propres handlers : propager émettrait chaque record une seconde fois par ceux du root.
    logger.propagate = False

    # Évite les doublons quand le logger est configuré plusieurs fois.
    if logger.handlers:
        return logger

    console = logging.StreamHandler(stream=_FluxConsole(console_stream()))
    console.setFormatter(_make_console_formatter())
    _add_console_filters(console)
    logger.addHandler(console)

    if os.environ.get("LOG_TO_FILE", "").lower() == "true":
        _attach_file_handler(logger, name, log_dir, _make_formatter())

    return logger


def setup_file_logger(name: str, log_dir: str) -> logging.Logger:
    """Logger à sortie fichier seule, pour un journal de détail que la console n'affiche pas. Même fichier et même opt-in `LOG_TO_FILE` que `setup_logger` ; sans `LOG_TO_FILE`, le logger n'écrit rien."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    if os.environ.get("LOG_TO_FILE", "").lower() == "true":
        _attach_file_handler(logger, name, log_dir, _make_formatter())
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def _attach_file_handler(
    logger: logging.Logger, name: str, log_dir: str, fmt: logging.Formatter
) -> None:
    """Ajoute au logger un fichier sous `PROJECT_ROOT/logs/`, ou s'en passe si le disque le refuse.

    Un système de fichiers en lecture seule — le conteneur de production est cloisonné ainsi — ou un répertoire fermé en écriture rend le fichier impossible. La journalisation retombe alors sur la seule sortie standard, que le runtime collecte, avec un avertissement : l'application démarre quand même.
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
    """Configure le root logger, que rejoignent les records des modules appelant `logging.getLogger(__name__)`.

    Sans ce handler, `logging` se rabat sur son handler de dernier recours : la ligne part sur la sortie d'erreur, sans format, hors de portée de l'écrivain de console. Elle s'inscrit alors au milieu de ce que le terminal affiche déjà.
    """
    root = logging.getLogger()
    root.setLevel(level)
    # Retire les handlers par défaut, qu'uvicorn peut ajouter ensuite.
    for h in list(root.handlers):
        root.removeHandler(h)
    # Sous pytest, `caplog` capte déjà les records et les affiche en cas d'échec : un handler de sortie standard les dupliquerait.
    if os.environ.get("PYTEST_VERSION") or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    handler = logging.StreamHandler(stream=_FluxConsole(console_stream()))
    handler.setFormatter(_make_console_formatter())
    _add_console_filters(handler)
    root.addHandler(handler)
