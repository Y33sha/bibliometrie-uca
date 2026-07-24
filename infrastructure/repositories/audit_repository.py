"""Adapter PostgreSQL pour l'écriture dans `audit_log`."""

from sqlalchemy import Connection, insert

from application.ports.repositories.audit_repository import AuditRepository
from domain.types import JsonValue
from infrastructure.db.tables import audit_log


class PgAuditRepository(AuditRepository):
    """Accès PostgreSQL sync à `audit_log` via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def record_event(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: int | None,
        payload: dict[str, JsonValue],
        user_id: str,
    ) -> None:
        self._conn.execute(
            insert(audit_log).values(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                payload=payload,
                user_id=user_id,
            )
        )
