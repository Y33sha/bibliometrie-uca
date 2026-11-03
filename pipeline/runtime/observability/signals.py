"""Signaux des phases qui interrogent des sources externes."""

import logging

from domain.pipeline_runs import PhaseStatus
from pipeline.runtime.observability.metrics import PhaseMetrics


def signal_source_unconfigured(
    metrics: PhaseMetrics, source: str, reason: str, *, logger: logging.Logger, phase: str
) -> None:
    """Marque comme sauté un accès à configuration manquante : identifiants ou périmètre d'interrogation.

    La phase se termine avec les accès configurés, en avertissement.

    Args:
        reason: motif du saut.
        phase: situe l'avertissement dans le journal.
    """
    logger.warning("%s : source %s non configurée — sautée : %s", phase, source, reason)
    metrics.signals.append(
        {
            "level": PhaseStatus.WARNING,
            "code": "source_unconfigured",
            "message": f"{source} non configurée — sautée : {reason}",
        }
    )


def signal_source_unavailable(
    metrics: PhaseMetrics, source: str, *, logger: logging.Logger, phase: str
) -> None:
    """Marque comme indisponible une source coupée en cours de tâche.

    La phase se termine avec les sources abouties, en avertissement. Le run suivant reprend les éléments non traités.
    """
    logger.warning(
        "%s : source %s coupée après une série de requêtes en échec, items reportés au prochain run",
        phase,
        source,
    )
    metrics.signals.append(
        {
            "level": PhaseStatus.WARNING,
            "code": "source_unavailable",
            "message": f"{source} coupée après une série de requêtes en échec, items reportés au prochain run",
        }
    )


def skipped(metrics: PhaseMetrics) -> bool:
    """Indique si l'accès est sauté avant tout traitement : source non configurée, ou indisponible sans élément traité."""
    codes = {s["code"] for s in metrics.signals}
    return "source_unconfigured" in codes or (metrics.total == 0 and "source_unavailable" in codes)
