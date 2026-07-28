"""Adapter PostgreSQL sync pour l'agrégat Perimeter."""

from sqlalchemy import Connection, delete, func, select, update

from application.ports.repositories.perimeter_repository import PerimeterRepository, PerimeterUpdate
from domain.errors import NotFoundError
from infrastructure.db.tables import perimeters


class PgPerimeterRepository(PerimeterRepository):
    """Accès PostgreSQL sync à la table `perimeters`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

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
