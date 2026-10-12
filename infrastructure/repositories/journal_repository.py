"""Adapter PostgreSQL pour l'édition de l'agrégat Journal dans l'administration.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP). La fusion de deux revues appartient au pipeline (`pipeline/publishing/journal_merge.py`).

Même contrat que les autres PgXxxRepository : exceptions du domaine, l'orchestration métier restant dans `application/services/journals/`.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple, cast

from sqlalchemy import Connection, delete, select, update

from application.ports.repositories.journal_repository import (
    JournalRepository,
    SharedTitleJournalPair,
)
from domain.errors import NotFoundError
from domain.journals.issns import JournalIssn
from domain.journals.journal import Journal, JournalType, ManualField, OaModel
from domain.normalize import normalize_text
from infrastructure.db.journal_issns import issns_by_journal
from infrastructure.db.rows import row_as
from infrastructure.db.tables import journal_issns, journals


class _JournalRow(NamedTuple):
    """Projection SQL `find_by_id` sur `journals`."""

    id: int
    title: str
    publisher_id: int | None
    openalex_id: str | None
    is_in_doaj: bool
    apc_amount: Decimal | None
    apc_currency: str | None
    oa_model: str | None
    journal_type: str | None
    is_academic: bool | None
    manual_fields: list[str]


def _journal_from_row(row: _JournalRow, issns: Sequence[JournalIssn]) -> Journal:
    """Mappe une row `journals` SQL vers l'aggregate `Journal`.

    Coerce les valeurs vers les types du domaine : `journal_type` et `is_academic`, nullables au schéma, retombent sur leur défaut (`unknown` / `True`). Les enums SQL `journal_type` et `oa_model` reprennent le vocabulaire du domaine, d'où la simple assertion de type.
    """
    return Journal(
        id=row.id,
        title=row.title,
        issns=list(issns),
        publisher_id=row.publisher_id,
        openalex_id=row.openalex_id,
        is_in_doaj=row.is_in_doaj,
        apc_amount=row.apc_amount,
        apc_currency=row.apc_currency,
        oa_model=cast(OaModel | None, row.oa_model),
        journal_type=cast(JournalType, row.journal_type)
        if row.journal_type is not None
        else JournalType.UNKNOWN,
        is_academic=row.is_academic if row.is_academic is not None else True,
        manual_fields=frozenset(ManualField(f) for f in row.manual_fields),
    )


class PgJournalRepository(JournalRepository):
    """Accès PostgreSQL à l'agrégat Journal via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Chargement de l'aggregate ──────────────────────────────────

    def find_by_id(self, journal_id: int) -> Journal | None:
        row = self._conn.execute(
            select(
                journals.c.id,
                journals.c.title,
                journals.c.publisher_id,
                journals.c.openalex_id,
                journals.c.is_in_doaj,
                journals.c.apc_amount,
                journals.c.apc_currency,
                journals.c.oa_model,
                journals.c.journal_type,
                journals.c.is_academic,
                journals.c.manual_fields,
            ).where(journals.c.id == journal_id)
        ).first()
        if row is None:
            return None
        issns = issns_by_journal(self._conn, [journal_id]).get(journal_id, ())
        return _journal_from_row(row_as(_JournalRow, row), issns)

    # ── Persistance de l'agrégat ───────────────────────────────────

    def save(self, journal: Journal) -> None:
        """Persiste une revue chargée : UPDATE de ses champs éditables par l'API et de ses ISSN. `title_normalized` est re-dérivé du titre ; les colonnes gérées par le pipeline (`publisher_id`, `openalex_id`, `is_in_doaj`) ne sont pas touchées. Un ISSN gardé conserve sa date de vérification Sudoc, un ISSN ajouté attend la sienne. Lève `NotFoundError` si l'id est absent."""
        result = self._conn.execute(
            update(journals)
            .where(journals.c.id == journal.id)
            .values(
                title=journal.title,
                title_normalized=normalize_text(journal.title),
                oa_model=journal.oa_model,
                journal_type=journal.journal_type,
                is_academic=journal.is_academic,
                apc_amount=journal.apc_amount,
                apc_currency=journal.apc_currency,
                manual_fields=sorted(journal.manual_fields),
            )
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Revue {journal.id} introuvable")
        self._save_issns(journal.id, journal.issns)

    def _save_issns(self, journal_id: int | None, issns: Sequence[JournalIssn]) -> None:
        values = [row.issn for row in issns]
        self._conn.execute(
            delete(journal_issns).where(
                journal_issns.c.journal_id == journal_id, journal_issns.c.issn.not_in(values)
            )
        )
        # Le drapeau ISSN-L se retire avant d'être reposé : une revue a au plus un ISSN-L.
        self._conn.execute(
            update(journal_issns)
            .where(journal_issns.c.journal_id == journal_id)
            .values(linking=False)
        )
        for row in issns:
            fields = {
                "support": row.support,
                "linking": row.linking,
                "status": row.status,
                "replaced_by": row.replaced_by,
            }
            kept = self._conn.execute(
                update(journal_issns)
                .where(journal_issns.c.journal_id == journal_id, journal_issns.c.issn == row.issn)
                .values(**fields)
            ).rowcount
            if not kept:
                self._conn.execute(
                    journal_issns.insert().values(issn=row.issn, journal_id=journal_id, **fields)
                )

    # ── Fusion ─────────────────────────────────────────────────────

    def find_shared_title_journal_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[SharedTitleJournalPair]:
        jt = journals.alias("jt")
        js = journals.alias("js")
        stmt = (
            select(
                jt.c.id.label("target_journal_id"),
                js.c.id.label("source_journal_id"),
                jt.c.title.label("t_title"),
                js.c.title.label("s_title"),
            )
            .select_from(jt.join(js, js.c.title_normalized == jt.c.title_normalized))
            .where(jt.c.publisher_id == target_publisher_id)
            .where(js.c.publisher_id == source_publisher_id)
        )
        rows = self._conn.execute(stmt).all()
        issns = issns_by_journal(
            self._conn, [r.target_journal_id for r in rows] + [r.source_journal_id for r in rows]
        )
        return [
            SharedTitleJournalPair(
                target_journal_id=r.target_journal_id,
                target_title=r.t_title,
                source_journal_id=r.source_journal_id,
                source_title=r.s_title,
                t_title=r.t_title,
                s_title=r.s_title,
                t_issns=list(issns.get(r.target_journal_id, ())),
                s_issns=list(issns.get(r.source_journal_id, ())),
            )
            for r in rows
        ]
