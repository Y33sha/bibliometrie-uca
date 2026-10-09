"""Adapter PostgreSQL du référentiel ROR."""

from collections.abc import Iterable, Sequence
from itertools import batched

from sqlalchemy import Connection, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization
from infrastructure.db.tables import ror_dump_imports, ror_organizations, ror_relations

_BATCH_SIZE = 5000


class PgRorRepository:
    """Implémentation PostgreSQL de `application.ports.repositories.ror_repository.RorRepository`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def replace_all(
        self,
        organizations: Sequence[RorOrganization],
        relations: Iterable[tuple[RorId, RorId]],
        *,
        version: str,
    ) -> None:
        self._conn.execute(delete(ror_relations))
        self._conn.execute(delete(ror_organizations))
        for batch in batched(organizations, _BATCH_SIZE):
            self._conn.execute(
                insert(ror_organizations),
                [
                    {
                        "ror_id": org.ror_id.value,
                        "name": org.name,
                        "country_code": org.country_code,
                        "types": sorted(org.types),
                        "status": org.status.value,
                    }
                    for org in batch
                ],
            )
        for batch in batched(relations, _BATCH_SIZE):
            self._conn.execute(
                insert(ror_relations),
                [
                    {"parent_ror_id": parent.value, "child_ror_id": child.value}
                    for parent, child in batch
                ],
            )
        self._conn.execute(
            pg_insert(ror_dump_imports)
            .values(version=version, imported_at=func.clock_timestamp())
            .on_conflict_do_update(
                index_elements=["version"], set_={"imported_at": func.clock_timestamp()}
            )
        )

    def last_imported_version(self) -> str | None:
        return self._conn.execute(
            select(ror_dump_imports.c.version)
            .order_by(ror_dump_imports.c.imported_at.desc())
            .limit(1)
        ).scalar_one_or_none()
