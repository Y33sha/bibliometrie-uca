"""Adapter PostgreSQL sync pour l'agrégat Perimeter."""

from typing import NamedTuple

from sqlalchemy import Connection, delete, func, select, update

from application.ports.repositories.perimeter_repository import PerimeterUpdate
from domain.errors import NotFoundError
from domain.perimeters.perimeter import Perimeter
from infrastructure.db.tables import perimeters
from infrastructure.queries.perimeter import refresh_perimeter_structures


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
                perimeters.c.root_structure_ids,
            ).where(perimeters.c.id == perimeter_id)
        ).first()
        if row is None:
            return None
        return _perimeter_from_row(_PerimeterRow(*row))

    # ── Liens structure ↔ perimeter ────────────────────────────────

    def remove_structure_from_all_perimeters(self, structure_id: int) -> None:
        self._conn.execute(
            update(perimeters)
            .where(perimeters.c.root_structure_ids.contains([structure_id]))
            .values(
                root_structure_ids=func.array_remove(
                    perimeters.c.root_structure_ids, structure_id
                )
            )
        )

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
        root_structure_ids: list[int],
    ) -> int:
        stmt = (
            perimeters.insert()
            .values(code=code, name=name, root_structure_ids=root_structure_ids)
            .returning(perimeters.c.id)
        )
        result = self._conn.execute(stmt)
        return result.scalar_one()

    def update_perimeter_fields(self, perimeter_id: int, fields: PerimeterUpdate) -> None:
        """UPDATE dynamique sur `perimeters` à partir des champs fournis.

        L'`UPDATE` rapporte les lignes appariées : zéro dit l'absence, sans lecture préalable. La non-vacuité des champs est vérifiée par le service.
        """
        data = fields.model_dump(exclude_unset=True)
        stmt = update(perimeters).where(perimeters.c.id == perimeter_id).values(**data)
        result = self._conn.execute(stmt)
        if result.rowcount == 0:
            raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    def get_perimeter_code(self, perimeter_id: int) -> str | None:
        result = self._conn.execute(
            select(perimeters.c.code).where(perimeters.c.id == perimeter_id)
        )
        return result.scalar_one_or_none()

    def delete_perimeter(self, perimeter_id: int) -> None:
        self._conn.execute(delete(perimeters).where(perimeters.c.id == perimeter_id))

    # ── Matérialisation ────────────────────────────────────────────

    def refresh_structures(self) -> None:
        """Reconstruit `perimeter_structures` (clôture récursive des racines de tous les
        périmètres). Commit laissé au caller (command handler)."""
        refresh_perimeter_structures(self._conn)
