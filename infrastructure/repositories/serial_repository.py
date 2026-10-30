"""Repository PostgreSQL de l'entité Serial, pour l'édition dans l'administration.

L'entité Publisher est dans `publisher_repository.py`. La fusion de deux revues relève du pipeline (`pipeline/transformation/publishing/serials/serial_merge.py`). Les erreurs sont celles du domaine ; l'orchestration est dans `application/services/serials/`.
"""

from collections.abc import Sequence
from typing import NamedTuple, cast

from sqlalchemy import Connection, delete, select, update

from application.ports.repositories.serial_repository import SerialRepository
from domain.errors import NotFoundError
from domain.normalize import normalize_text
from domain.publishers.merge import SharedTitlePair
from domain.serials.issns import SerialIssn
from domain.serials.serial import ManualField, OaModel, Serial, SerialType
from infrastructure.db.rows import row_as
from infrastructure.db.tables import serial_issns, serials
from infrastructure.repositories.serial_issns import issns_by_serial


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


def _serial_from_row(row: _SerialRow, issns: Sequence[SerialIssn]) -> Serial:
    """Revue de domaine d'une ligne de `serials`.

    `serial_type` et `is_academic`, nullables, prennent leur défaut (`unknown`, vrai). Les enums SQL `serial_type` et `oa_model` reprennent le vocabulaire du domaine : une assertion de type suffit.
    """
    return Serial(
        id=row.id,
        title=row.title,
        issns=list(issns),
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
        issns = issns_by_serial(self._conn, [serial_id]).get(serial_id, ())
        return _serial_from_row(row_as(_SerialRow, row), issns)

    # ── Écriture ───────────────────────────────────────────────────

    def save(self, serial: Serial) -> None:
        """Écrit les champs modifiables par l'API d'une revue chargée, et ses ISSN. Le titre normalisé se recalcule ; les colonnes que tient le pipeline (`publisher_id`, `openalex_id`, `is_in_doaj`) restent. Un ISSN gardé garde sa date de vérification Sudoc, un ISSN ajouté attend la sienne. Lève `NotFoundError` si l'id est absent."""
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
        self._save_issns(serial.id, serial.issns)

    def _save_issns(self, serial_id: int | None, issns: Sequence[SerialIssn]) -> None:
        values = [row.issn for row in issns]
        self._conn.execute(
            delete(serial_issns).where(
                serial_issns.c.serial_id == serial_id, serial_issns.c.issn.not_in(values)
            )
        )
        # Le drapeau ISSN-L se retire avant d'être reposé : une revue a au plus un ISSN-L.
        self._conn.execute(
            update(serial_issns).where(serial_issns.c.serial_id == serial_id).values(linking=False)
        )
        for row in issns:
            fields = {
                "support": row.support,
                "linking": row.linking,
                "status": row.status,
            }
            kept = self._conn.execute(
                update(serial_issns)
                .where(serial_issns.c.serial_id == serial_id, serial_issns.c.issn == row.issn)
                .values(**fields)
            ).rowcount
            if not kept:
                self._conn.execute(
                    serial_issns.insert().values(issn=row.issn, serial_id=serial_id, **fields)
                )

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
        issns = issns_by_serial(
            self._conn, [r.target_serial_id for r in rows] + [r.source_serial_id for r in rows]
        )
        return [
            SharedTitlePair(
                target_serial_id=r.target_serial_id,
                target_title=r.target_title,
                target_issns=issns.get(r.target_serial_id, ()),
                source_serial_id=r.source_serial_id,
                source_title=r.source_title,
                source_issns=issns.get(r.source_serial_id, ()),
            )
            for r in rows
        ]
