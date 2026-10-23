"""Accès à une source : tout appel à une API tierce passe par `access_source`.

L'accès contrôle les identifiants de la source et saute l'étape, avec un avertissement, s'ils manquent. Il pose le circuit-breaker de la source, que lisent les clients HTTP. Il signale une source indisponible ou un circuit coupé : la phase passe en avertissement, et le run suivant reprend les éléments non traités.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from pipeline.http.circuit_breaker import (
    DEFAULT_THRESHOLD,
    SourceCircuitBreaker,
    SourceUnavailableError,
    source_circuit_breaker,
)
from pipeline.runtime.context import CredentialsMissing
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import (
    signal_source_unavailable,
    signal_source_unconfigured,
)


def access_source(
    source: str,
    execute: Callable[[], PhaseMetrics],
    *,
    phase: str,
    logger: logging.Logger,
    credentials_missing: CredentialsMissing,
    threshold: int | None = None,
) -> PhaseMetrics:
    """Exécute `execute` sur `source` : identifiants contrôlés, circuit-breaker posé, indisponibilité signalée.

    `phase` situe les avertissements dans le journal. `credentials_missing` contrôle les identifiants de la source.
    """
    if reason := credentials_missing(source):
        metrics = PhaseMetrics()
        signal_source_unconfigured(metrics, source, reason, logger=logger, phase=phase)
        return metrics
    with source_circuit_breaker(source, threshold=threshold or DEFAULT_THRESHOLD) as breaker:
        try:
            metrics = execute()
        except SourceUnavailableError:
            metrics = PhaseMetrics()
            signal_source_unavailable(metrics, source, logger=logger, phase=phase)
    _signal_if_tripped(metrics, breaker)
    return metrics


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
