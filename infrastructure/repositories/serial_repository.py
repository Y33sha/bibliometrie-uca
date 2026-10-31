"""Repository PostgreSQL de l'entité Serial, pour l'édition dans l'administration.

L'entité Publisher est dans `publisher_repository.py`. La fusion de deux revues relève du pipeline (`pipeline/transformation/publishing/serials/serial_merge.py`). Les erreurs sont celles du domaine ; l'orchestration est dans `application/services/serials/`.
"""

from typing import NamedTuple, cast

from sqlalchemy import Connection, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.repositories.serial_repository import SerialRepository
from domain.errors import NotFoundError
from domain.normalize import normalize_text
from domain.publishers.merge import SharedTitlePair
from domain.serials.serial import ManualField, OaModel, Serial, SerialType
from infrastructure.db.rows import row_as
from infrastructure.db.tables import serial_title_decisions, serials
from infrastructure.sql_fragments import serial_issnl


class _SerialRow(NamedTuple):
    """Projection SQL `find_by_id` sur `serials`."""

    id: int
    title: str
    publisher_id: int | None
    openalex_id: str | None
    is_in_doaj: bool
    oa_model: str | None
    serial_type: str | None
    is_academic: bool | None
    manual_fields: list[str]


def _serial_from_row(row: _SerialRow) -> Serial:
    """Renvoie la revue de domaine d'une ligne de `serials`.

    `serial_type` et `is_academic`, nullables, prennent leur défaut (`unknown`, vrai). Les enums SQL `serial_type` et `oa_model` reprennent le vocabulaire du domaine : une assertion de type suffit.
    """
    return Serial(
        id=row.id,
        title=row.title,
        publisher_id=row.publisher_id,
        openalex_id=row.openalex_id,
        is_in_doaj=row.is_in_doaj,
        oa_model=cast(OaModel | None, row.oa_model),
        serial_type=cast(SerialType, row.serial_type)
        if row.serial_type is not None
        else SerialType.UNKNOWN,
        is_academic=row.is_academic if row.is_academic is not None else True,
        manual_fields=frozenset(ManualField(f) for f in row.manual_fields),
    )


class PgSerialRepository(SerialRepository):
    """Accès PostgreSQL à l'entité Serial via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Chargement ─────────────────────────────────────────────────

    def find_by_id(self, serial_id: int) -> Serial | None:
        row = self._conn.execute(
            select(
                serials.c.id,
                serials.c.title,
                serials.c.publisher_id,
                serials.c.openalex_id,
                serials.c.is_in_doaj,
                serials.c.oa_model,
                serials.c.serial_type,
                serials.c.is_academic,
                serials.c.manual_fields,
            ).where(serials.c.id == serial_id)
        ).first()
        if row is None:
            return None
        return _serial_from_row(row_as(_SerialRow, row))

    def issnl_of(self, serial_id: int) -> str | None:
        return self._conn.execute(
            text(f"SELECT {serial_issnl(':id')}"), {"id": serial_id}
        ).scalar_one_or_none()

    def record_title_decision(self, source_id: int, target_id: int) -> None:
        source = self._conn.execute(
            select(serials.c.title_normalized, serials.c.publisher_id).where(
                serials.c.id == source_id
            )
        ).one()
        self._conn.execute(
            pg_insert(serial_title_decisions)
            .values(
                title_normalized=source.title_normalized,
                publisher_id=source.publisher_id,
                serial_id=target_id,
            )
            .on_conflict_do_update(
                constraint="uq_serial_title_decisions", set_={"serial_id": target_id}
            )
        )
        # Une décision qui désignait la revue absorbée la suit.
        self._conn.execute(
            update(serial_title_decisions)
            .where(serial_title_decisions.c.serial_id == source_id)
            .values(serial_id=target_id)
        )

    # ── Écriture ───────────────────────────────────────────────────

    def save(self, serial: Serial) -> None:
        """Écrit les champs modifiables par l'API d'une revue chargée. Lève `NotFoundError` si l'id est absent.

        Le titre normalisé se recalcule. Les colonnes tenues par le pipeline (`publisher_id`, `openalex_id`, `is_in_doaj`) restent.
        """
        result = self._conn.execute(
            update(serials)
            .where(serials.c.id == serial.id)
            .values(
                title=serial.title,
                title_normalized=normalize_text(serial.title),
                oa_model=serial.oa_model,
                serial_type=serial.serial_type,
                is_academic=serial.is_academic,
                manual_fields=sorted(serial.manual_fields),
            )
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Revue {serial.id} introuvable")

    # ── Revues homonymes de deux éditeurs ──────────────────────────

    def find_shared_title_serial_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[SharedTitlePair]:
        jt = serials.alias("jt")
        js = serials.alias("js")
        stmt = (
            select(
                jt.c.id.label("target_serial_id"),
                js.c.id.label("source_serial_id"),
                jt.c.title.label("target_title"),
                js.c.title.label("source_title"),
            )
            .select_from(jt.join(js, js.c.title_normalized == jt.c.title_normalized))
            .where(jt.c.publisher_id == target_publisher_id)
            .where(js.c.publisher_id == source_publisher_id)
        )
        rows = self._conn.execute(stmt).all()
        return [
            SharedTitlePair(
                target_serial_id=r.target_serial_id,
                target_title=r.target_title,
                target_issnl=self.issnl_of(r.target_serial_id),
                source_serial_id=r.source_serial_id,
                source_title=r.source_title,
                source_issnl=self.issnl_of(r.source_serial_id),
            )
            for r in rows
        ]
