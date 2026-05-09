"""Adapter PostgreSQL pour les ports périmètres.

- `PgPerimeterQueries` / `PgAsyncPerimeterQueries` : thin wrapper autour
  des fonctions de `infrastructure.perimeter` (`AsyncPerimeterQueries`
  côté lecteur `persons`).
- `PgAsyncPerimetersAdminQueries` : listing complet pour /api/perimeters.
"""

from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.perimeter import (
    async_get_perimeter_structure_ids,
    async_get_persons_structure_ids_list,
    get_perimeter_structure_ids,
    get_persons_structure_ids_list,
)


class PgPerimeterQueries:
    """Adapter PostgreSQL pour `application.ports.perimeter.PerimeterQueries`."""

    def get_persons_structure_ids_list(self, cur: Any) -> list[int]:
        return get_persons_structure_ids_list(cur)


class PgAsyncPerimeterQueries:
    """Variante async — adapter pour `AsyncPerimeterQueries`."""

    async def get_persons_structure_ids_list(self, cur: Any) -> list[int]:
        return await async_get_persons_structure_ids_list(cur)


class PgAsyncPerimetersAdminQueries:
    """Adapter SA pour `application.ports.perimeters_queries.AsyncPerimetersAdminQueries`."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_perimeters_with_structures(self) -> list[dict[str, Any]]:
        """Liste tous les périmètres avec leurs structures racines + le décompte
        après descente récursive (CTE `async_get_perimeter_structure_ids`)."""
        perim_rows = (
            await self._conn.execute(
                text(
                    "SELECT id, code, name, description, structure_ids FROM perimeters ORDER BY id"
                )
            )
        ).all()
        perimeters: list[dict[str, Any]] = []
        for p_row in perim_rows:
            p = dict(p_row._mapping)
            root_ids = p["structure_ids"] or []
            if root_ids:
                struct_rows = (
                    await self._conn.execute(
                        text(
                            "SELECT id, name, acronym, code FROM structures "
                            "WHERE id = ANY(:ids) ORDER BY name"
                        ),
                        {"ids": root_ids},
                    )
                ).all()
                p["structures"] = [dict(r._mapping) for r in struct_rows]
            else:
                p["structures"] = []
            resolved = await async_get_perimeter_structure_ids(self._conn, p["code"])
            p["structure_count"] = len(resolved)
            perimeters.append(p)
        return perimeters


class PgPerimetersAdminQueries:
    """Variante sync de `PgAsyncPerimetersAdminQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_perimeters_with_structures(self) -> list[dict[str, Any]]:
        perim_rows = self._conn.execute(
            text("SELECT id, code, name, description, structure_ids FROM perimeters ORDER BY id")
        ).all()
        perimeters: list[dict[str, Any]] = []
        for p_row in perim_rows:
            p = dict(p_row._mapping)
            root_ids = p["structure_ids"] or []
            if root_ids:
                struct_rows = self._conn.execute(
                    text(
                        "SELECT id, name, acronym, code FROM structures "
                        "WHERE id = ANY(:ids) ORDER BY name"
                    ),
                    {"ids": root_ids},
                ).all()
                p["structures"] = [dict(r._mapping) for r in struct_rows]
            else:
                p["structures"] = []
            resolved = get_perimeter_structure_ids(self._conn, p["code"])
            p["structure_count"] = len(resolved)
            perimeters.append(p)
        return perimeters
