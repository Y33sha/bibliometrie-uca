"""Chronométrage et signaux partagés des phases qui ventilent par source / canal.

Utilisés par les phases à interrogation externe (`extract`, `cross_imports`, `refresh_stale`, `oa_status`) : `timed_metrics` mesure la durée d'une sous-tâche (distincte de la durée totale de la phase), `signal_source_unconfigured` marque un accès API non configuré comme sauté sans interrompre le run.
"""

import logging
import time
from collections.abc import Callable, Sequence

from application.pipeline.metrics import PhaseMetrics


def timed_metrics(fn: Callable[[], PhaseMetrics]) -> tuple[PhaseMetrics, float]:
    """Exécute `fn` et renvoie ses métriques avec sa durée d'exécution (s).

    Pour les phases qui ventilent leurs indicateurs par source / canal et ont besoin d'une durée par sous-tâche.
    """
    started = time.time()
    result = fn()
    return result, time.time() - started


def signal_source_unconfigured(
    metrics: PhaseMetrics, source: str, reason: str, *, logger: logging.Logger, phase: str
) -> None:
    """Marque un accès à une API tierce non configuré comme sauté (avertissement).

    Un accès dont la configuration manque (credentials, ou pour l'extraction bulk le périmètre d'interrogation) n'interrompt pas le run : la phase se termine avec les accès configurés, son point passe en ambre et le motif s'affiche au détail. Même canal de signaux que le circuit-breaker. `reason` est le motif d'absence, `phase` le contexte pour le log.
    """
    logger.warning("%s : source %s non configurée — sautée : %s", phase, source, reason)
    metrics.signals.append(
        {
            "level": "warning",
            "code": "source_unconfigured",
            "message": f"{source} non configurée — sautée : {reason}",
        }
    )


def signal_source_unavailable(
    metrics: PhaseMetrics, source: str, *, logger: logging.Logger, phase: str
) -> None:
    """Marque une source indisponible (retries épuisés sur 429/5xx/réseau, ou circuit-breaker déclenché) comme sautée.

    La phase se termine avec les sources qui ont abouti, son point passe en ambre, et les items non traités sont repris au run suivant (phases de rattrapage idempotentes). Même canal de signaux que `signal_source_unconfigured` et le circuit-breaker.
    """
    logger.warning(
        "%s : source %s indisponible — sautée, items reportés au prochain run", phase, source
    )
    metrics.signals.append(
        {
            "level": "warning",
            "code": "source_unavailable",
            "message": f"{source} indisponible — sautée, items reportés au prochain run",
        }
    )


def select_targets(
    base: Sequence[str], sources: set[str] | None, *, include_wos: bool
) -> list[str]:
    """Sources à interroger : `base` moins WoS (opt-in via `include_wos`), restreintes au filtre `sources` s'il est fourni, dans l'ordre canonique de `base`.

    Prologue commun aux phases à interrogation externe, en amont de `filter_configured`. L'ordre stable garantit des logs et un dispatch déterministes.
    """
    eligible = set(base) - (set() if include_wos else {"wos"})
    if sources:
        eligible &= sources
    return [t for t in base if t in eligible]


def filter_configured(
    targets: list[str],
    metrics: PhaseMetrics,
    *,
    credentials_missing: Callable[[str], str | None],
    logger: logging.Logger,
    phase: str,
) -> list[str]:
    """Garde les sources configurées, signale les autres (`source_unconfigured`).

    `credentials_missing(source)` rend le motif d'absence de credentials, ou `None` si la source est configurée. La détection (lecture des credentials) est injectée par le composition-root ; l'assemblage des signaux vit ici, côté application.
    """
    configured: list[str] = []
    for target in targets:
        reason = credentials_missing(target)
        if reason:
            signal_source_unconfigured(metrics, target, reason, logger=logger, phase=phase)
        else:
            configured.append(target)
    return configured
