"""Signaux et bilans des phases qui interrogent des sources externes."""

import logging
from collections.abc import Callable, Mapping

from domain.pipeline_runs import PhaseStatus
from domain.sources.registry import LOOKUP_SOURCES, source_label
from pipeline.runtime.observability.metrics import PhaseMetrics


def _display_name(source: str) -> str:
    """Renvoie le nom affiché de l'accès : celui d'une source du registre, sinon `source` tel quel."""
    return source_label(source) if source in LOOKUP_SOURCES else source


def signal_source_unconfigured(
    metrics: PhaseMetrics, source: str, reason: str, *, logger: logging.Logger
) -> None:
    """Marque comme sauté un accès à configuration manquante : identifiants ou périmètre d'interrogation.

    La phase se termine avec les accès configurés, en avertissement.

    Args:
        reason: motif du saut.
    """
    name = _display_name(source)
    logger.warning("Source %s non configurée — sautée : %s", name, reason)
    metrics.signals.append(
        {
            "level": PhaseStatus.WARNING,
            "code": "source_unconfigured",
            "message": f"{name} non configurée — sautée : {reason}",
        }
    )


def signal_source_unavailable(
    metrics: PhaseMetrics, source: str, *, logger: logging.Logger, reason: str | None = None
) -> None:
    """Marque comme indisponible une source coupée en cours de tâche, ou un dump inaccessible.

    La phase se termine avec les sources abouties, en avertissement. Le run suivant reprend les éléments non traités.

    Args:
        reason: motif écrit au journal et dans le signal. Par défaut, la coupure de la source après une série de requêtes en échec.
    """
    message = reason or (
        f"Source {_display_name(source)} coupée après une série de requêtes en échec,"
        " items reportés au prochain run"
    )
    logger.warning("%s", message)
    metrics.signals.append(
        {"level": PhaseStatus.WARNING, "code": "source_unavailable", "message": message}
    )


def signal_dump_unrecognized(
    metrics: PhaseMetrics, message: str, *, logger: logging.Logger
) -> None:
    """Marque un dump téléchargé sans entrée reconnue, signe d'un changement de son format. Le référentiel reste en l'état, et la phase se termine en avertissement."""
    logger.warning("%s", message)
    metrics.signals.append(
        {"level": PhaseStatus.WARNING, "code": "dump_unrecognized", "message": message}
    )


def skipped(metrics: PhaseMetrics) -> bool:
    """Indique si l'accès est sauté avant tout traitement : source non configurée, ou indisponible sans élément traité."""
    codes = {s["code"] for s in metrics.signals}
    return "source_unconfigured" in codes or (metrics.total == 0 and "source_unavailable" in codes)


def assemble_by_source(
    by_task: Mapping[str, PhaseMetrics],
    row: Callable[[PhaseMetrics], Mapping[str, float | None]],
    key: Callable[[str], str] = str,
) -> PhaseMetrics:
    """Renvoie la somme des métriques des tâches, avec la table d'observabilité des accès non sautés : une ligne par tâche, de clé `key(nom de la tâche)` et de colonnes `row(métriques)`."""
    metrics = PhaseMetrics()
    rows: list[dict[str, object]] = []
    for name, task_metrics in by_task.items():
        metrics.merge(task_metrics)
        if not skipped(task_metrics):
            rows.append({"key": key(name), **row(task_metrics)})
    if rows:
        metrics.details["table"] = {"rows": rows}
    return metrics
