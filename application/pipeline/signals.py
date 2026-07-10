"""Chronométrage et signaux partagés des phases qui ventilent par source / canal.

Utilisés par les phases à interrogation externe (`extract`, `cross_imports`, `refresh_stale`,
`oa_status`) : `timed_metrics` mesure la durée d'une sous-tâche (distincte de la durée totale de
la phase), `signal_source_unconfigured` marque un accès API non configuré comme sauté sans
interrompre le run.
"""

import logging
import time
from collections.abc import Callable

from application.pipeline.metrics import PhaseMetrics


def timed_metrics(fn: Callable[[], PhaseMetrics]) -> tuple[PhaseMetrics, float]:
    """Exécute `fn` et renvoie ses métriques avec sa durée d'exécution (s).

    Pour les phases qui ventilent leurs indicateurs par source / canal et ont besoin d'une durée
    par sous-tâche.
    """
    started = time.time()
    result = fn()
    return result, time.time() - started


def signal_source_unconfigured(
    metrics: PhaseMetrics, source: str, reason: str, *, logger: logging.Logger, phase: str
) -> None:
    """Marque un accès à une API tierce non configuré comme sauté (avertissement).

    Un accès dont la configuration manque (credentials, ou pour l'extraction bulk le périmètre
    d'interrogation) n'interrompt pas le run : la phase se termine avec les accès configurés, son
    point passe en ambre et le motif s'affiche au détail. Même canal de signaux que le
    circuit-breaker. `reason` est le motif d'absence, `phase` le contexte pour le log.
    """
    logger.warning("%s : source %s non configurée — sautée : %s", phase, source, reason)
    metrics.signals.append(
        {
            "level": "warning",
            "code": "source_unconfigured",
            "message": f"{source} non configurée — sautée : {reason}",
        }
    )


def filter_configured(
    targets: list[str],
    metrics: PhaseMetrics,
    *,
    credentials_missing: Callable[[str], str | None],
    logger: logging.Logger,
    phase: str,
) -> list[str]:
    """Garde les sources configurées, signale les autres (`source_unconfigured`).

    `credentials_missing(source)` rend le motif d'absence de credentials, ou `None` si la source
    est configurée. La détection (lecture des credentials) est injectée par le composition-root ;
    l'assemblage des signaux vit ici, côté application.
    """
    configured: list[str] = []
    for target in targets:
        reason = credentials_missing(target)
        if reason:
            signal_source_unconfigured(metrics, target, reason, logger=logger, phase=phase)
        else:
            configured.append(target)
    return configured
