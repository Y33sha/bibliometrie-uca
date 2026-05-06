"""Query services pour les paramètres applicatifs (table `config`).

Lookups par clé pour l'application (extraction, OA email, etc.) restent
dans `infrastructure/app_config.py` ; ce module héberge les queries
servies par le router admin (listing complet pour édition) ainsi que
l'adapter du port `application.ports.config.AsyncConfigStore`.
"""

import json
from typing import Any


async def list_config_async(cur: Any) -> list[dict[str, Any]]:
    """Tous les paramètres applicatifs triés par clé."""
    await cur.execute("SELECT key, value, description, updated_at FROM config ORDER BY key")
    return await cur.fetchall()


class PgAsyncConfig:
    """Adapter PostgreSQL async pour `application.ports.config.AsyncConfigStore`."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    async def config_key_exists(self, key: str) -> bool:
        await self._cur.execute("SELECT key FROM config WHERE key = %s", (key,))
        return (await self._cur.fetchone()) is not None

    async def update_config_value(self, key: str, value: Any) -> dict:
        await self._cur.execute(
            """
            UPDATE config SET value = %s::jsonb, updated_at = now()
            WHERE key = %s
            RETURNING key, value, description, updated_at
            """,
            (json.dumps(value), key),
        )
        return await self._cur.fetchone()

    async def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        await self._cur.execute(
            """
            SELECT key FROM config
            WHERE key LIKE 'perimeter_%%' AND value #>> '{}' = %s
            """,
            (perimeter_code,),
        )
        rows = await self._cur.fetchall()
        return [r["key"] for r in rows]
