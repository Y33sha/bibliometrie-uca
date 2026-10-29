"""Signaux des phases qui interrogent des sources externes."""

import logging
from collections.abc import Sequence, Set

from domain.pipeline_runs import PhaseStatus
from domain.sources.registry import PROFILES
from pipeline.runtime.observability.metrics import PhaseMetrics


def signal_source_unconfigured(
    metrics: PhaseMetrics, source: str, reason: str, *, logger: logging.Logger, phase: str
) -> None:
    """Marque comme sauté un accès dont la configuration manque : identifiants, ou périmètre d'interrogation. La phase se termine avec les accès configurés, en avertissement. `reason` : motif ; `phase` : contexte du journal."""
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
    """Marque comme indisponible une source coupée en cours de tâche. La phase se termine avec les sources qui ont abouti, en avertissement, et le run suivant reprend les éléments non traités."""
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


def select_targets(base: Sequence[str], sources: Set[str], *, include_wos: bool) -> list[str]:
    """Sources à interroger : celles de `base` qui font partie de `sources`, moins les sources sur option (`SourceProfile.opt_in`) sans `include_wos`, dans l'ordre de `base`."""
    opt_in = set() if include_wos else {s for s, p in PROFILES.items() if p.opt_in}
    eligible = (set(base) & sources) - opt_in
    return [t for t in base if t in eligible]


def skipped(metrics: PhaseMetrics) -> bool:
    """Accès sauté avant tout traitement : source non configurée, ou indisponible sans élément traité."""
    codes = {s["code"] for s in metrics.signals}
    return "source_unconfigured" in codes or (metrics.total == 0 and "source_unavailable" in codes)
