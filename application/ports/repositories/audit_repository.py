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
        entity_type: str,
        entity_id: int | None,
        payload: dict[str, JsonValue],
        user_id: str,
    ) -> None:
        """Insère un événement d'audit.

        Args:
            entity_id: `None` si l'entité touchée disparaît sans équivalent (suppression).
            payload: données sérialisées en `jsonb`.
        """
        ...
