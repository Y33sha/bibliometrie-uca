"""Contexte d'exécution commun aux phases : transaction gérée et circuit-breaker de source.

Les imports d'infrastructure restent locaux aux fonctions : charger ce module ne charge aucun client de source.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.signals import signal_source_unavailable
from application.ports.pipeline.circuit_breaker import SourceUnavailableError

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from infrastructure.sources.circuit_breaker import SourceCircuitBreaker


def open_tx() -> AbstractContextManager[Connection]:
    """Fabrique de transaction gérée (port `OpenTransaction`) : commit sur succès, rollback sur erreur, fermeture, et tolérance aux commits par lots."""
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.transaction import managed_transaction

    return managed_transaction(get_sync_engine())


@contextmanager
def circuit_breaker(source: str, *, threshold: int | None = None) -> Iterator[SourceCircuitBreaker]:
    """Pose le circuit-breaker de `source` dans la ContextVar que lisent les clients HTTP, le temps du bloc."""
    from infrastructure.sources.circuit_breaker import (
        DEFAULT_THRESHOLD,
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )

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
