"""Lectures du rapport de cohérence entre `structure_tutelles` et le référentiel ROR.

`PgRorCoherenceQueries` implémente le port `application.ports.read_models.ror_queries`.
"""

from collections.abc import Iterable

from sqlalchemy import Connection, text

from application.ports.read_models.ror_queries import StructureRor
from domain.structures.identifiers import RorId


class PgRorCoherenceQueries:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def structures(self) -> list[StructureRor]:
        rows = self._conn.execute(text("SELECT id, code, ror_id FROM structures ORDER BY code"))
        return [StructureRor(id=r.id, code=r.code, ror_id=RorId.try_parse(r.ror_id)) for r in rows]

    def tutelles(self) -> list[tuple[int, int]]:
        rows = self._conn.execute(text("SELECT parent_id, child_id FROM structure_tutelles"))
        return [(r.parent_id, r.child_id) for r in rows]

    def perimeter_structure_ids(self) -> frozenset[int]:
        rows = self._conn.execute(text("SELECT DISTINCT structure_id FROM perimeter_structures"))
        return frozenset(rows.scalars())

    def ror_relations(self) -> list[tuple[RorId, RorId]]:
        rows = self._conn.execute(text("SELECT parent_ror_id, child_ror_id FROM ror_relations"))
        return [(RorId(r.parent_ror_id), RorId(r.child_ror_id)) for r in rows]

    def ror_names(self, ror_ids: Iterable[RorId]) -> dict[RorId, str]:
        rows = self._conn.execute(
            text("SELECT ror_id, name FROM ror_organizations WHERE ror_id = ANY(:ids)"),
            {"ids": [r.value for r in ror_ids]},
        )
        return {RorId(r.ror_id): r.name for r in rows}
