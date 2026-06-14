"""Circuit-breaker par source (implémentation) : coupe les fetches d'une source à
bout de budget API (429) ou en panne (5xx / réseau) au lieu de backoff + retry sur
chaque item.

Un compteur d'échecs **consécutifs** par source, partagé entre les requêtes
concurrentes d'une phase via une `ContextVar` : `+1` sur requête échouée
(429 / 5xx / réseau après retries), **remis à 0 au premier succès**. Au seuil, le
breaker est `tripped` : `http_request_with_retry_async` court-circuite les
requêtes suivantes (`SourceUnavailableError`) et la boucle de fetch saute le reste
de la source — les items non traités sont retentés au run suivant (phases de
rattrapage idempotentes).

Vit côté `infrastructure` parce que c'est le helper HTTP infra qui le manipule
(check / record). Les orchestrateurs `application/` ne consultent que l'état
`tripped` via le protocole `application.ports.pipeline.circuit_breaker.CircuitBreaker`
(implémenté ici en duck typing). Le câblage (création, pose de la ContextVar) est
fait par la composition root `run_pipeline`.

Seuil à 10 (et non 5) pour ne pas abandonner sur un seul batch d'échecs
concurrents, qui peut être un incident ponctuel.

Concurrence : tout tourne dans l'event loop (mono-thread) ; `record_*` n'ont pas
d'`await`, donc atomiques vis-à-vis des autres coroutines — pas de race sur le
compteur partagé.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

DEFAULT_THRESHOLD = 10


class SourceUnavailableError(Exception):
    """Le breaker d'une source a tripé : source à bout (budget/panne), à sauter
    pour la phase en cours."""

    def __init__(self, source: str) -> None:
        super().__init__(f"source {source} indisponible (circuit-breaker tripé)")
        self.source = source


class SourceCircuitBreaker:
    """Compteur d'échecs consécutifs d'une source. `tripped` à `threshold`.

    Implémente structurellement `application.ports.pipeline.circuit_breaker.CircuitBreaker`
    (attribut `tripped`)."""

    def __init__(self, source: str, *, threshold: int = DEFAULT_THRESHOLD) -> None:
        self.source = source
        self.threshold = threshold
        self._consecutive = 0
        self.tripped = False

    def record_success(self) -> None:
        self._consecutive = 0

    def record_failure(self) -> None:
        self._consecutive += 1
        if self._consecutive >= self.threshold:
            self.tripped = True

    def check(self) -> None:
        """Lève `SourceUnavailableError` si le breaker est tripé."""
        if self.tripped:
            raise SourceUnavailableError(self.source)


_current_breaker: ContextVar[SourceCircuitBreaker | None] = ContextVar(
    "source_circuit_breaker", default=None
)


def get_current_breaker() -> SourceCircuitBreaker | None:
    """Breaker de la phase courante (None si aucun n'est posé)."""
    return _current_breaker.get()


def set_current_breaker(breaker: SourceCircuitBreaker | None) -> Token:
    """Pose le breaker courant ; retourne le token à passer à `reset_current_breaker`."""
    return _current_breaker.set(breaker)


def reset_current_breaker(token: Token) -> None:
    _current_breaker.reset(token)
