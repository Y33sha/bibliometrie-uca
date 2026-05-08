"""Port AuditRepository — contrat d'écriture dans `audit_log`.

Implémenté par `infrastructure/repositories/audit_repository.py` (sync)
et `async_audit_repository.py` (async). La logique de filtrage par
`user_id` (no-op hors contexte HTTP) reste dans `application/audit.py` ;
le port n'expose qu'une opération brute d'insertion.
"""

from typing import Any, Protocol


class AuditRepository(Protocol):
    """Contrat d'écriture sync dans audit_log."""

    def record_event(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: int | None,
        payload: dict[str, Any],
        user_id: str,
    ) -> None: ...


class AsyncAuditRepository(Protocol):
    """Variante async d'AuditRepository."""

    async def record_event(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: int | None,
        payload: dict[str, Any],
        user_id: str,
    ) -> None: ...
