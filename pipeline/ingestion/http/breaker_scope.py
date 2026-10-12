"""Exécution d'une phase ou d'une étape sous le circuit-breaker d'une source, et signalement de sa coupure."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from pipeline.ingestion.http.circuit_breaker import (
    DEFAULT_THRESHOLD,
    SourceCircuitBreaker,
    SourceUnavailableError,
    reset_current_breaker,
    set_current_breaker,
)
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unavailable


@contextmanager
def circuit_breaker(source: str, *, threshold: int | None = None) -> Iterator[SourceCircuitBreaker]:
    """Pose le circuit-breaker de `source` dans la ContextVar que lisent les clients HTTP, le temps du bloc."""
    breaker = SourceCircuitBreaker(source, threshold=threshold or DEFAULT_THRESHOLD)
    token = set_current_breaker(breaker)
    try:
        yield breaker
    finally:
        reset_current_breaker(token)


def signal_if_tripped(metrics: PhaseMetrics, breaker: SourceCircuitBreaker) -> None:
    """Marque la phase en avertissement quand le circuit-breaker d'une source a coupé, après une série de 429 ou de 5xx. Les phases de rattrapage étant idempotentes, le run suivant reprend les documents non traités."""
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


def under_circuit_breaker(
    source: str,
    execute: Callable[[SourceCircuitBreaker], PhaseMetrics],
    *,
    phase: str,
    logger: logging.Logger,
    threshold: int | None = None,
) -> PhaseMetrics:
    """Exécute `execute` sous le circuit-breaker de `source`.

    Une source indisponible donne des métriques vides, signalées : la transaction englobante commit ce qui précède l'indisponibilité.
    """
    with circuit_breaker(source, threshold=threshold) as breaker:
        try:
            metrics = execute(breaker)
        except SourceUnavailableError:
            metrics = PhaseMetrics()
            signal_source_unavailable(metrics, source, logger=logger, phase=phase)
    signal_if_tripped(metrics, breaker)
    return metrics


@dataclass(frozen=True)
class UnderCircuitBreaker:
    """Exécute une phase sous le circuit-breaker de `source`, et la signale quand il a coupé."""

    source: str
    phase: Phase

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        with circuit_breaker(self.source) as breaker:
            metrics = self.phase.run(ctx)
        signal_if_tripped(metrics, breaker)
        return metrics
