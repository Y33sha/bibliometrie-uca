"""Lecture et écriture des lignes de `journal_issns`."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Connection, Row, select

from domain.journals.issns import IssnStatus, IssnSupport, JournalIssn
from infrastructure.db.tables import journal_issns


def journal_issn(row: Row[tuple[object, ...]]) -> JournalIssn:
    """ISSN d'une ligne de `journal_issns`."""
    return JournalIssn(
        issn=str(row.issn),
        support=IssnSupport(row.support) if row.support else None,
        linking=bool(row.linking),
        status=IssnStatus(row.status),
        replaced_by=str(row.replaced_by) if row.replaced_by else None,
    )


def issn_values(
    row: JournalIssn, *, journal_id: int | None, checked_at: datetime | None = None
) -> dict[str, object]:
    """Valeurs d'insertion d'un ISSN. Un ISSN sans revue n'est pas un ISSN-L."""
    return {
        "issn": row.issn,
        "journal_id": journal_id,
        "support": row.support,
        "linking": row.linking and journal_id is not None,
        "status": row.status,
        "replaced_by": row.replaced_by,
        "sudoc_checked_at": checked_at,
    }


def issns_by_journal(
    conn: Connection, journal_ids: Sequence[int] | None = None
) -> dict[int, tuple[JournalIssn, ...]]:
    """ISSN de chaque revue, dans l'ordre d'enregistrement. Sans `journal_ids`, ceux de toutes les revues."""
    stmt = select(journal_issns).where(journal_issns.c.journal_id.is_not(None))
    if journal_ids is not None:
        stmt = stmt.where(journal_issns.c.journal_id.in_(journal_ids))
    issns: dict[int, list[JournalIssn]] = {}
    for r in conn.execute(stmt.order_by(journal_issns.c.id)):
        issns.setdefault(r.journal_id, []).append(journal_issn(r))
    return {journal_id: tuple(rows) for journal_id, rows in issns.items()}
