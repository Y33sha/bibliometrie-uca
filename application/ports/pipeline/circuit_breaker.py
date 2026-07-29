"""Port : circuit-breaker par source, consulté par les boucles de fetch.

L'implémentation concrète (`SourceCircuitBreaker`) et la `ContextVar` partagée vivent côté `infrastructure.sources.circuit_breaker` — c'est le helper HTTP (infra) qui les manipule. L'exception `SourceUnavailableError` est définie ici, côté port, pour que les orchestrateurs `application/` puissent l'attraper sans dépendre de l'infrastructure (DDD : application → ports, jamais → infrastructure).
"""

from typing import Protocol


class SourceUnavailableError(Exception):
    """Une source est indisponible pour le run en cours : budget API épuisé (429) ou panne (5xx / réseau).

    Levée par le helper HTTP quand une requête a épuisé ses retries sur une erreur retryable, ou par le circuit-breaker quand la source cumule trop d'échecs. Les orchestrateurs l'attrapent pour sauter la source sans interrompre le run ; les items non traités repartent au run suivant (phases de rattrapage idempotentes).
    """

    def __init__(self, source: str) -> None:
        super().__init__(f"source {source} indisponible (retries épuisés ou circuit-breaker déclenché)")
        self.source = source


class CircuitBreaker(Protocol):
    """Vue minimale dont une boucle de fetch a besoin : l'état `tripped`.

    `True` = la source a accumulé trop d'échecs consécutifs (budget/panne) et doit être sautée pour la phase en cours.
    """

    tripped: bool
