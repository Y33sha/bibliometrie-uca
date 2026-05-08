"""Adapter PostgreSQL async pour l'écriture dans `audit_log`.

Mode dispatch (cur psycopg | AsyncConnection SA). Phase 4 supprimera
la branche psycopg.
"""

from typing import Any

from psycopg.types.json import Jsonb as Json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class PgAsyncAuditRepository:
    """Accès PostgreSQL async à audit_log.

    Accepte un curseur psycopg ou une AsyncConnection SQLAlchemy.
    """

    def __init__(self, conn_or_cur: Any) -> None:
        self._conn = conn_or_cur
        self._is_sa = isinstance(conn_or_cur, AsyncConnection)

    async def record_event(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: int | None,
        payload: dict[str, Any],
        user_id: str,
    ) -> None:
        if self._is_sa:
            await self._conn.execute(
                text(
                    "INSERT INTO audit_log "
                    "(event_type, aggregate_type, aggregate_id, payload, user_id) "
                    "VALUES (:event_type, :aggregate_type, :aggregate_id, "
                    "        CAST(:payload AS jsonb), :user_id)"
                ),
                {
                    "event_type": event_type,
                    "aggregate_type": aggregate_type,
                    "aggregate_id": aggregate_id,
                    "payload": _json_dumps(payload),
                    "user_id": user_id,
                },
            )
            return
        await self._conn.execute(
            """
            INSERT INTO audit_log (event_type, aggregate_type, aggregate_id,
                                   payload, user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (event_type, aggregate_type, aggregate_id, Json(payload), user_id),
        )


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value)
