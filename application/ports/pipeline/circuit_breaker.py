"""Port : circuit-breaker par source, consulté par les boucles de fetch.

L'implémentation concrète (`SourceCircuitBreaker`), la `ContextVar` partagée et
l'exception `SourceUnavailableError` vivent côté
`infrastructure.sources.circuit_breaker` — c'est le helper HTTP (infra) qui les
manipule. Les orchestrateurs `application/` ne dépendent que de ce protocole pour
consulter l'état du breaker (DDD : application → ports, jamais → infrastructure).
"""

from typing import Protocol


class CircuitBreaker(Protocol):
    """Vue minimale dont une boucle de fetch a besoin : l'état `tripped`.

    `True` = la source a accumulé trop d'échecs consécutifs (budget/panne) et
    doit être sautée pour la phase en cours.
    """

    tripped: bool
