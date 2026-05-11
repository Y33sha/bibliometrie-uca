"""Adapter PostgreSQL pour les ports périmètres.

- `PgPerimeterQueries` : thin wrapper autour des fonctions de
  `infrastructure.perimeter` (lecteur `persons`).
- `PgPerimetersAdminQueries` : listing complet pour /api/perimeters.
"""

from typing import Any

from sqlalchemy import Connection, text

from infrastructure.perimeter import (
    get_perimeter_structure_ids,
    get_persons_structure_ids_list,
)


class PgPerimeterQueries:
    """Adapter PostgreSQL pour `application.ports.perimeter.PerimeterQueries`."""

    def get_persons_structure_ids_list(self, conn: Connection) -> list[int]:
        return get_persons_structure_ids_list(conn)


class PgPerimetersAdminQueries:
    """Adapter SA pour `application.ports.perimeters_queries.PerimetersAdminQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_perimeters_with_structures(self) -> list[dict[str, Any]]:
        """Liste tous les périmètres avec leurs structures racines + le décompte
        après descente récursive (CTE `get_perimeter_structure_ids`)."""
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
