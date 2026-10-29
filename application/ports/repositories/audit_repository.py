"""Port AuditRepository : écriture dans `audit_log`.

Le port insère seulement. Le choix de consigner, selon la requête, relève de `application/audit_log.py`.
"""

from typing import Protocol

from domain.types import JsonValue


class AuditRepository(Protocol):
    """Écriture dans `audit_log`."""

    def record_event(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: int | None,
        payload: dict[str, JsonValue],
        user_id: str,
    ) -> None:
        """Insère un événement d'audit. `aggregate_id` : NULL si l'entité affectée n'a pas d'équivalent survivant (suppression). `payload` : données utiles sérialisées en `jsonb`."""
        ...
