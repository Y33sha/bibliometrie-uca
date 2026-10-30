"""Accès à une source : tout appel à une API tierce passe par `access_source`.

L'accès contrôle les identifiants de la source. S'ils manquent, l'étape est sautée avec un avertissement. L'accès pose le circuit-breaker de la source, lu par les clients HTTP. Une source coupée, par une exception ou par `trip_source`, est signalée : la phase passe en avertissement, et le run suivant reprend les éléments non traités.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from pipeline.http.circuit_breaker import (
    DEFAULT_THRESHOLD,
    SourceUnavailableError,
    source_circuit_breaker,
)
from pipeline.runtime.context import CredentialsMissing, RequestBudget
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
    request_budget: RequestBudget,
    threshold: int | None = None,
) -> PhaseMetrics:
    """Exécute `execute` sur `source` : identifiants contrôlés, circuit-breaker posé, indisponibilité signalée.

    Args:
        phase: situe les avertissements dans le journal.
    """
    if reason := credentials_missing(source):
        metrics = PhaseMetrics()
        signal_source_unconfigured(metrics, source, reason, logger=logger, phase=phase)
        return metrics
    with source_circuit_breaker(
        source, threshold=threshold or DEFAULT_THRESHOLD, max_per_second=request_budget(source)
    ) as breaker:
        try:
            metrics = execute()
        except SourceUnavailableError:
            metrics = PhaseMetrics()
            breaker.trip()
    if breaker.tripped:
        signal_source_unavailable(metrics, source, logger=logger, phase=phase)
    return metrics
