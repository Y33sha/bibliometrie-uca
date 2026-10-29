"""Circuit-breaker par source : coupe les requêtes d'une source à bout de budget (429) ou en panne (5xx, réseau).

`source_circuit_breaker` pose dans une `ContextVar` le compteur des échecs consécutifs de la source, que partagent les requêtes de la tâche. Une requête en échec après ses nouvelles tentatives l'incrémente, un succès le remet à zéro. Au seuil, le breaker coupe : les clients HTTP lèvent `SourceUnavailableError` pour les requêtes suivantes, et le run suivant reprend les éléments non traités.

Le seuil de 10 absorbe une série ponctuelle d'échecs de requêtes concurrentes. `record_success` et `record_failure` sont sans `await`, donc atomiques entre les coroutines qui partagent le compteur.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pipeline.http.pace import Pace

DEFAULT_THRESHOLD = 10

__all__ = [
    "DEFAULT_THRESHOLD",
    "SourceCircuitBreaker",
    "SourceUnavailableError",
    "get_current_breaker",
    "source_circuit_breaker",
    "source_tripped",
    "trip_source",
]


class SourceUnavailableError(Exception):
    """Source indisponible pour le run, levée par le client HTTP après ses nouvelles tentatives, ou par le breaker coupé. L'accès à la source l'attrape pour sauter la source sans interrompre le run."""

    def __init__(self, source: str) -> None:
        super().__init__(
            f"source {source} indisponible (retries épuisés ou circuit-breaker déclenché)"
        )
        self.source = source


class SourceCircuitBreaker:
    """Compteur d'échecs consécutifs d'une source, `tripped` à `threshold`, et rythme de ses requêtes (`pace`, `None` sans plafond)."""

    def __init__(
        self, source: str, *, threshold: int = DEFAULT_THRESHOLD, pace: Pace | None = None
    ) -> None:
        self.source = source
        self.threshold = threshold
        self.pace = pace
        self._consecutive = 0
        self.tripped = False

    def record_success(self) -> None:
        self._consecutive = 0

    def record_failure(self) -> None:
        self._consecutive += 1
        if self._consecutive >= self.threshold:
            self.tripped = True

    def trip(self) -> None:
        """Coupe la source : une boucle y renonce après une requête en échec."""
        self.tripped = True

    def check(self) -> None:
        """Lève `SourceUnavailableError` si le breaker est déclenché."""
        if self.tripped:
            raise SourceUnavailableError(self.source)


_current_breaker: ContextVar[SourceCircuitBreaker | None] = ContextVar(
    "source_circuit_breaker", default=None
)


def get_current_breaker() -> SourceCircuitBreaker | None:
    """Breaker de la tâche courante, ou `None`."""
    return _current_breaker.get()


def trip_source() -> None:
    """Coupe la source de la tâche courante, si un breaker est posé : une boucle y renonce sur `SourceUnavailableError`."""
    breaker = _current_breaker.get()
    if breaker is not None:
        breaker.trip()


def source_tripped() -> bool:
    """Vrai si le breaker de la tâche courante a coupé. Une boucle qui range les échecs en résultats le consulte pour s'arrêter."""
    breaker = _current_breaker.get()
    return breaker is not None and breaker.tripped


@contextmanager
def source_circuit_breaker(
    source: str, *, threshold: int = DEFAULT_THRESHOLD, max_per_second: float | None = None
) -> Iterator[SourceCircuitBreaker]:
    """Pose le breaker de `source` dans la ContextVar le temps du bloc. Les requêtes suivent le rythme de `max_per_second`, sans plafond à `None`."""
    pace = Pace(max_per_second) if max_per_second else None
    breaker = SourceCircuitBreaker(source, threshold=threshold, pace=pace)
    token = _current_breaker.set(breaker)
    try:
        yield breaker
    finally:
        _current_breaker.reset(token)
