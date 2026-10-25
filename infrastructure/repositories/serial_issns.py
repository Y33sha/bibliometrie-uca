"""Lecture et écriture des lignes de `serial_issns`."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Connection, Row, select

from domain.serials.issns import IssnStatus, IssnSupport, SerialIssn
from infrastructure.db.tables import serial_issns


def journal_issn(row: Row[tuple[object, ...]]) -> SerialIssn:
    """ISSN d'une ligne de `serial_issns`."""
    return SerialIssn(
        issn=str(row.issn),
        support=IssnSupport(row.support) if row.support else None,
        linking=bool(row.linking),
        status=IssnStatus(row.status),
        replaced_by=str(row.replaced_by) if row.replaced_by else None,
    )


def issn_values(
    row: SerialIssn, *, serial_id: int | None, checked_at: datetime | None = None
) -> dict[str, object]:
    """Valeurs d'insertion d'un ISSN. Un ISSN sans revue n'est pas un ISSN-L."""
    return {
        "issn": row.issn,
        "serial_id": serial_id,
        "support": row.support,
        "linking": row.linking and serial_id is not None,
        "status": row.status,
        "replaced_by": row.replaced_by,
        "sudoc_checked_at": checked_at,
    }


def issns_by_serial(
    conn: Connection, serial_ids: Sequence[int] | None = None
) -> dict[int, tuple[SerialIssn, ...]]:
    """ISSN de chaque revue, dans l'ordre d'enregistrement. Sans `serial_ids`, ceux de toutes les revues."""
    stmt = select(serial_issns).where(serial_issns.c.serial_id.is_not(None))
    if serial_ids is not None:
        stmt = stmt.where(serial_issns.c.serial_id.in_(serial_ids))
    issns: dict[int, list[SerialIssn]] = {}
    for r in conn.execute(stmt.order_by(serial_issns.c.id)):
        issns.setdefault(r.serial_id, []).append(journal_issn(r))
    return {serial_id: tuple(rows) for serial_id, rows in issns.items()}
