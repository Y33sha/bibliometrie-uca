"""Query services pour les paramètres applicatifs (table `config`).

Lookups par clé pour l'application (extraction, OA email, etc.) restent
dans `infrastructure/app_config.py` ; ce module héberge les queries
servies par le router admin (listing complet pour édition) ainsi que
l'adapter du port `application.ports.config.AsyncConfigStore`.
"""

from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.tables import config


async def list_config_async(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Tous les paramètres applicatifs triés par clé."""
    result = await conn.execute(
        select(config.c.key, config.c.value, config.c.description, config.c.updated_at).order_by(
            config.c.key
        )
    )
    return [dict(r._mapping) for r in result]


class PgAsyncConfig:
    """Adapter PostgreSQL async pour `application.ports.config.AsyncConfigStore`."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def config_key_exists(self, key: str) -> bool:
        result = await self._conn.execute(select(config.c.key).where(config.c.key == key))
        return result.first() is not None

    async def update_config_value(self, key: str, value: Any) -> dict:
        stmt = (
            update(config)
            .where(config.c.key == key)
            .values(value=value, updated_at=func.now())
            .returning(config.c.key, config.c.value, config.c.description, config.c.updated_at)
        )
        result = await self._conn.execute(stmt)
        return dict(result.one()._mapping)

    async def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        # Le double # dans `value #>> '{}'` extrait le scalar JSON. SA Core
        # n'a pas d'opérateur direct ; on passe par text() avec bind nommé.
        result = await self._conn.execute(
            text("SELECT key FROM config WHERE key LIKE 'perimeter_%' AND value #>> '{}' = :code"),
            {"code": perimeter_code},
        )
        return [r.key for r in result]
