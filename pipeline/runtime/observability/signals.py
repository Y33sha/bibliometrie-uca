"""Signaux partagés des phases qui ventilent par source ou par canal.

Utilisés par les phases à interrogation externe (`harvest`, `fetch_missing`, `fetch_stale`, `oa_status`) : `signal_source_unconfigured` marque un accès API non configuré comme sauté sans interrompre le run.
"""

import logging
from collections.abc import Sequence, Set

from domain.pipeline_runs import PhaseStatus
from domain.sources.registry import PROFILES
from pipeline.runtime.observability.metrics import PhaseMetrics


def signal_source_unconfigured(
    metrics: PhaseMetrics, source: str, reason: str, *, logger: logging.Logger, phase: str
) -> None:
    """Marque un accès à une API tierce non configuré comme sauté (avertissement).

    Un accès dont la configuration manque (credentials, ou pour l'extraction bulk le périmètre d'interrogation) n'interrompt pas le run : la phase se termine avec les accès configurés, son point passe en ambre et le motif s'affiche au détail. Même canal de signaux que le circuit-breaker. `reason` est le motif d'absence, `phase` le contexte pour le log.
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
    """Marque une source coupée en cours de tâche comme indisponible.

    La phase se termine avec les sources qui ont abouti, son point passe en ambre, et les items non traités sont repris au run suivant (phases de rattrapage idempotentes). Même canal de signaux que `signal_source_unconfigured` et le circuit-breaker.
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


def select_targets(base: Sequence[str], sources: Set[str], *, include_wos: bool) -> list[str]:
    """Sources à interroger : celles de `base` qui font partie de `sources`, moins les sources sur option (`SourceProfile.opt_in`) sans `include_wos`, dans l'ordre de `base`.

    Prologue commun aux phases à interrogation externe. L'ordre stable garantit des logs et un dispatch déterministes.
    """
    opt_in = set() if include_wos else {s for s, p in PROFILES.items() if p.opt_in}
    eligible = (set(base) & sources) - opt_in
    return [t for t in base if t in eligible]


def skipped(metrics: PhaseMetrics) -> bool:
    """Accès sauté avant tout traitement : source non configurée, ou indisponible sans élément traité."""
    codes = {s["code"] for s in metrics.signals}
    return "source_unconfigured" in codes or (metrics.total == 0 and "source_unavailable" in codes)
