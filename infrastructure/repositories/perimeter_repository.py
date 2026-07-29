"""Adapter PostgreSQL sync pour l'agrégat Perimeter."""

from typing import NamedTuple

from sqlalchemy import Connection, delete, func, select, update

from application.ports.repositories.perimeter_repository import PerimeterRepository
from domain.errors import NotFoundError
from domain.perimeters.perimeter import Perimeter
from infrastructure.db.tables import perimeters


class _PerimeterRow(NamedTuple):
    """Projection SQL `find_by_id` sur `perimeters`."""

    id: int
    code: str
    name: str
    root_structure_ids: list[int]


def _perimeter_from_row(row: _PerimeterRow) -> Perimeter:
    """Mapping d'une row `perimeters` SQL vers l'aggregate `Perimeter`."""
    return Perimeter(
        id=row.id,
        code=row.code,
        name=row.name,
        root_structure_ids=tuple(row.root_structure_ids or ()),
    )


class PgPerimeterRepository(PerimeterRepository):
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
                perimeters.c.root_structure_ids,
            ).where(perimeters.c.id == perimeter_id)
        ).first()
        if row is None:
            return None
        return _perimeter_from_row(_PerimeterRow(**row._mapping))

    # ── Liens structure ↔ perimeter ────────────────────────────────

    def remove_structure_from_all_perimeters(self, structure_id: int) -> None:
        self._conn.execute(
            update(perimeters)
            .where(perimeters.c.root_structure_ids.contains([structure_id]))
            .values(
                root_structure_ids=func.array_remove(perimeters.c.root_structure_ids, structure_id)
            )
        )

    # ── CRUD ───────────────────────────────────────────────────────

    def perimeter_code_exists(self, code: str) -> bool:
        result = self._conn.execute(select(perimeters.c.id).where(perimeters.c.code == code))
        return result.first() is not None

    def add(self, perimeter: Perimeter) -> int:
        """Insère un périmètre neuf et retourne son id."""
        return self._conn.execute(
            perimeters.insert()
            .values(
                code=perimeter.code,
                name=perimeter.name,
                root_structure_ids=list(perimeter.root_structure_ids),
            )
            .returning(perimeters.c.id)
        ).scalar_one()

    def save(self, perimeter: Perimeter) -> None:
        """Persiste un périmètre chargé : UPDATE de ses champs éditables (`code` immuable exclu). Lève `NotFoundError` si l'id est absent."""
        result = self._conn.execute(
            update(perimeters)
            .where(perimeters.c.id == perimeter.id)
            .values(
                name=perimeter.name,
                root_structure_ids=list(perimeter.root_structure_ids),
            )
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Périmètre {perimeter.id} introuvable")

    def get_perimeter_code(self, perimeter_id: int) -> str | None:
        result = self._conn.execute(
            select(perimeters.c.code).where(perimeters.c.id == perimeter_id)
        )
        return result.scalar_one_or_none()

    def delete_perimeter(self, perimeter_id: int) -> None:
        self._conn.execute(delete(perimeters).where(perimeters.c.id == perimeter_id))
