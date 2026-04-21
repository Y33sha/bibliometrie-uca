"""Adapter PostgreSQL async pour `config` et `perimeters` (§2.12).

Parallèle à infrastructure/repositories/config_repository.py — même
contrat, curseur async.
"""

import json
from typing import Any


class PgAsyncConfigRepository:
    """Accès PostgreSQL async aux agrégats Config et Perimeter."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    # ── Table config (clé / valeur JSON) ───────────────────────────

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

    # ── Perimeters — structures membres ────────────────────────────

    async def add_structure_to_perimeter(
        self,
        perimeter_id: int,
        structure_id: int,
    ) -> bool:
        await self._cur.execute(
            """
            UPDATE perimeters
            SET structure_ids = array_append(structure_ids, %s)
            WHERE id = %s AND NOT structure_ids @> ARRAY[%s::int]
            RETURNING id
            """,
            (structure_id, perimeter_id, structure_id),
        )
        return (await self._cur.fetchone()) is not None

    async def remove_structure_from_perimeter(
        self,
        perimeter_id: int,
        structure_id: int,
    ) -> bool:
        await self._cur.execute(
            """
            UPDATE perimeters
            SET structure_ids = array_remove(structure_ids, %s)
            WHERE id = %s
            RETURNING id
            """,
            (structure_id, perimeter_id),
        )
        return (await self._cur.fetchone()) is not None

    # ── Perimeters — CRUD ──────────────────────────────────────────

    async def perimeter_exists(self, perimeter_id: int) -> bool:
        await self._cur.execute(
            "SELECT id FROM perimeters WHERE id = %s",
            (perimeter_id,),
        )
        return (await self._cur.fetchone()) is not None

    async def perimeter_code_exists(self, code: str) -> bool:
        await self._cur.execute(
            "SELECT id FROM perimeters WHERE code = %s",
            (code,),
        )
        return (await self._cur.fetchone()) is not None

    async def create_perimeter(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
    ) -> int:
        await self._cur.execute(
            """
            INSERT INTO perimeters (code, name, description, structure_ids)
            VALUES (%s, %s, %s, '{}')
            RETURNING id
            """,
            (code, name, description),
        )
        row = await self._cur.fetchone()
        return row["id"]

    async def update_perimeter_fields(self, perimeter_id: int, fields: dict) -> None:
        sets = ", ".join(f"{k} = %s" for k in fields)
        await self._cur.execute(
            f"UPDATE perimeters SET {sets} WHERE id = %s",
            list(fields.values()) + [perimeter_id],
        )

    async def get_perimeter_code(self, perimeter_id: int) -> str | None:
        await self._cur.execute(
            "SELECT code FROM perimeters WHERE id = %s",
            (perimeter_id,),
        )
        row = await self._cur.fetchone()
        return row["code"] if row else None

    async def delete_perimeter(self, perimeter_id: int) -> None:
        await self._cur.execute(
            "DELETE FROM perimeters WHERE id = %s",
            (perimeter_id,),
        )
