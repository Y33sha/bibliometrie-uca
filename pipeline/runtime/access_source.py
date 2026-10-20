"""Accès à une source : tout appel à une API tierce passe par `access_source`.

L'accès contrôle les identifiants de la source et saute l'étape, avec un avertissement, s'ils manquent. Il pose le circuit-breaker de la source, que lisent les clients HTTP. Il signale une source indisponible ou un circuit coupé : la phase passe en avertissement, et le run suivant reprend les éléments non traités.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from pipeline.http.circuit_breaker import (
    DEFAULT_THRESHOLD,
    SourceCircuitBreaker,
    SourceUnavailableError,
    reset_current_breaker,
    set_current_breaker,
)
from pipeline.runtime import config
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import (
    signal_source_unavailable,
    signal_source_unconfigured,
)


def access_source(
    source: str,
    execute: Callable[[SourceCircuitBreaker], PhaseMetrics],
    *,
    phase: str,
    logger: logging.Logger,
    threshold: int | None = None,
) -> PhaseMetrics:
    """Exécute `execute` sur `source` : identifiants contrôlés, circuit-breaker posé, indisponibilité signalée.

    `execute` reçoit le circuit-breaker, que ses boucles consultent pour s'arrêter quand il coupe. `phase` situe les avertissements dans le journal.
    """
    if reason := config.source_credentials_missing(source):
        metrics = PhaseMetrics()
        signal_source_unconfigured(metrics, source, reason, logger=logger, phase=phase)
        return metrics
    with _circuit_breaker(source, threshold=threshold) as breaker:
        try:
            metrics = execute(breaker)
        except SourceUnavailableError:
            metrics = PhaseMetrics()
            signal_source_unavailable(metrics, source, logger=logger, phase=phase)
    _signal_if_tripped(metrics, breaker)
    return metrics


@contextmanager
def _circuit_breaker(
    source: str, *, threshold: int | None = None
) -> Iterator[SourceCircuitBreaker]:
    """Pose le circuit-breaker de `source` dans la ContextVar que lisent les clients HTTP, le temps du bloc."""
    breaker = SourceCircuitBreaker(source, threshold=threshold or DEFAULT_THRESHOLD)
    token = set_current_breaker(breaker)
    try:
        yield breaker
    finally:
        reset_current_breaker(token)


def _signal_if_tripped(metrics: PhaseMetrics, breaker: SourceCircuitBreaker) -> None:
    """Marque la phase en avertissement quand le circuit-breaker a coupé, après une série de 429 ou de 5xx."""
    if breaker.tripped:
        metrics.signals.append(
            {
                "level": "warning",
                "code": "source_unavailable",
                "message": (
                    f"{breaker.source} : arrêt après une série d'échecs (429/5xx), "
                    "items reportés au prochain run"
                ),
            }
        )
