"""Circuit-breaker par source (implémentation) : coupe les fetches d'une source à bout de budget API (429) ou en panne (5xx / réseau).

Un compteur d'échecs **consécutifs** par source, partagé au sein d'une phase via une `ContextVar` : `+1` sur requête échouée (429 / 5xx / réseau après retries), **remis à 0 au premier succès**. Au seuil, le breaker est `tripped` : les deux helpers HTTP — `http_request_with_retry` et sa variante async — court-circuitent les requêtes suivantes (`SourceUnavailableError`) et la boucle de fetch saute le reste de la source ; les items non traités sont retentés au run suivant (phases de rattrapage idempotentes).

L'accès à la source le pose dans la ContextVar par `source_circuit_breaker`, et signale sa coupure. Le client HTTP le manipule (check / record). Les boucles qui rangent un échec en résultat consultent `source_tripped()` pour s'arrêter. Une boucle qui renonce à la source sur `SourceUnavailableError` la coupe (`trip_source`).

Seuil à 10 échecs consécutifs : encaisse un batch d'échecs concurrents ponctuel avant de couper la source.

Concurrence : `record_*` sont sans `await`, atomiques vis-à-vis des autres coroutines — pas de race quand les requêtes async d'une même phase partagent le compteur. Les appelants du helper sync (moissonneurs page à page, clients de préfixes DOI, enrichissement des revues) fetchent en séquence.
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
    """Une source est indisponible pour le run en cours : budget API épuisé (429) ou panne (5xx / réseau).

    Levée par le helper HTTP quand une requête a épuisé ses retries sur une erreur retryable, ou par le circuit-breaker quand la source cumule trop d'échecs. Les orchestrateurs l'attrapent pour sauter la source sans interrompre le run ; les items non traités repartent au run suivant (phases de rattrapage idempotentes).
    """

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
    """Breaker de la phase courante (None si aucun n'est posé)."""
    return _current_breaker.get()


def trip_source() -> None:
    """Coupe la source de la phase courante. Sans breaker posé, ne fait rien."""
    breaker = _current_breaker.get()
    if breaker is not None:
        breaker.trip()


def source_tripped() -> bool:
    """`True` si le breaker de la phase courante a coupé."""
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
