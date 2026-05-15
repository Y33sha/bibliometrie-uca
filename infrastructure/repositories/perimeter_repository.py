"""Adapter PostgreSQL sync pour l'agrégat Perimeter."""

from typing import Any

from sqlalchemy import Connection, Row, delete, func, select, update

from domain.perimeters.perimeter import Perimeter
from infrastructure.db.tables import perimeters


def _perimeter_from_row(row: Row[Any]) -> Perimeter:
    """Mapping d'une row `perimeters` SQL vers l'aggregate `Perimeter`."""
    return Perimeter(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        structure_ids=tuple(row.structure_ids or ()),
    )


class PgPerimeterRepository:
    """Accès PostgreSQL sync à la table `perimeters`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Chargement de l'aggregate ──────────────────────────────────

    def find_by_id(self, perimeter_id: int) -> Perimeter | None:
        row = self._conn.execute(
            select(
                perimeters.c.id,
                perimeters.c.code,
                perimeters.c.name,
                perimeters.c.description,
                perimeters.c.structure_ids,
            ).where(perimeters.c.id == perimeter_id)
        ).first()
        if row is None:
            return None
        return _perimeter_from_row(row)

    # ── Liens structure ↔ perimeter ────────────────────────────────

    def add_structure_to_perimeter(self, perimeter_id: int, structure_id: int) -> bool:
        stmt = (
            update(perimeters)
            .where(perimeters.c.id == perimeter_id)
            .where(~perimeters.c.structure_ids.contains([structure_id]))
            .values(structure_ids=func.array_append(perimeters.c.structure_ids, structure_id))
            .returning(perimeters.c.id)
        )
        result = self._conn.execute(stmt)
        return result.first() is not None

    def remove_structure_from_perimeter(self, perimeter_id: int, structure_id: int) -> bool:
        stmt = (
            update(perimeters)
            .where(perimeters.c.id == perimeter_id)
            .values(structure_ids=func.array_remove(perimeters.c.structure_ids, structure_id))
            .returning(perimeters.c.id)
        )
        result = self._conn.execute(stmt)
        return result.first() is not None

    # ── CRUD ───────────────────────────────────────────────────────

    def perimeter_exists(self, perimeter_id: int) -> bool:
        result = self._conn.execute(select(perimeters.c.id).where(perimeters.c.id == perimeter_id))
        return result.first() is not None

    def perimeter_code_exists(self, code: str) -> bool:
        result = self._conn.execute(select(perimeters.c.id).where(perimeters.c.code == code))
        return result.first() is not None

    def create_perimeter(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
    ) -> int:
        stmt = (
            perimeters.insert()
            .values(code=code, name=name, description=description, structure_ids=[])
            .returning(perimeters.c.id)
        )
        result = self._conn.execute(stmt)
        return result.scalar_one()

    def update_perimeter_fields(self, perimeter_id: int, fields: dict) -> None:
        stmt = update(perimeters).where(perimeters.c.id == perimeter_id).values(**fields)
        self._conn.execute(stmt)

    def get_perimeter_code(self, perimeter_id: int) -> str | None:
        result = self._conn.execute(
            select(perimeters.c.code).where(perimeters.c.id == perimeter_id)
        )
        return result.scalar_one_or_none()

    def delete_perimeter(self, perimeter_id: int) -> None:
        self._conn.execute(delete(perimeters).where(perimeters.c.id == perimeter_id))
