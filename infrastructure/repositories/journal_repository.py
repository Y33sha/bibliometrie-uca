"""Adapter PostgreSQL pour l'édition et la fusion curées de l'agrégat Journal.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP). Le trouve-ou-crée et l'enrichissement, alimentés par le pipeline, vivent dans `infrastructure/pipeline/journals.py`.

Même contrat que les autres PgXxxRepository : exceptions du domaine, l'orchestration métier restant dans `application/services/journals/`.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple, cast

from sqlalchemy import Connection, delete, func, select, text, update

from application.ports.repositories.journal_repository import (
    JournalRepository,
    SharedTitleJournalPair,
)
from domain.errors import NotFoundError
from domain.journals.issns import JournalIssn
from domain.journals.journal import Journal, JournalType, OaModel
from domain.normalize import normalize_text
from infrastructure.db.journal_issns import issns_by_journal
from infrastructure.db.rows import row_as
from infrastructure.db.tables import journal_issns, journal_name_forms, journals
from infrastructure.pipeline.authorships.pub_counts import (
    refresh_journal_pub_count,
    refresh_publisher_pub_count,
)


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
            ).where(journals.c.id == journal_id)
        ).first()
        if row is None:
            return None
        issns = issns_by_journal(self._conn, [journal_id]).get(journal_id, ())
        return _journal_from_row(row_as(_JournalRow, row), issns)

    # ── Persistance de l'agrégat ───────────────────────────────────

    def save(self, journal: Journal) -> None:
        """Persiste une revue chargée : UPDATE de ses champs éditables par l'API et de ses ISSN. `title_normalized` est re-dérivé du titre ; les colonnes gérées par le pipeline (`publisher_id`, `openalex_id`, `apc_currency`) ne sont pas touchées. Un ISSN gardé conserve sa date de vérification Sudoc, un ISSN ajouté attend la sienne. Lève `NotFoundError` si l'id est absent."""
        result = self._conn.execute(
            update(journals)
            .where(journals.c.id == journal.id)
            .values(
                title=journal.title,
                title_normalized=normalize_text(journal.title),
                oa_model=journal.oa_model,
                journal_type=journal.journal_type,
                is_academic=journal.is_academic,
                is_in_doaj=journal.is_in_doaj,
                apc_amount=journal.apc_amount,
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

    def merge_journal_into(self, target_id: int, source_id: int) -> None:
        # publications, source_publications et apc_payments vivent hors de la MetaData de `tables.py` : accès en `text()`.
        self._conn.execute(
            text("UPDATE publications SET journal_id = :t WHERE journal_id = :s"),
            {"t": target_id, "s": source_id},
        )
        self._conn.execute(
            text("UPDATE source_publications SET journal_id = :t WHERE journal_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # journal_name_forms (anti-doublon) : forme/publisher commun → on garde la cible.
        self._conn.execute(
            text("""
                UPDATE journal_name_forms SET journal_id = :t
                WHERE journal_id = :s
                  AND (form_normalized, COALESCE(publisher_id, 0)) NOT IN (
                      SELECT form_normalized, COALESCE(publisher_id, 0)
                      FROM journal_name_forms WHERE journal_id = :t
                  )
            """),
            {"t": target_id, "s": source_id},
        )
        self._conn.execute(
            delete(journal_name_forms).where(journal_name_forms.c.journal_id == source_id)
        )

        self._conn.execute(
            text("UPDATE apc_payments SET journal_id = :t WHERE journal_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # Les ISSN de la source rejoignent la cible avec leur support et leur statut, à vérifier dans le Sudoc ; un ISSN
        # que la cible porte déjà reste le sien, et l'ISSN-L de la cible l'emporte.
        self._conn.execute(
            text("""
                DELETE FROM journal_issns s
                WHERE s.journal_id = :s
                  AND EXISTS (SELECT 1 FROM journal_issns t WHERE t.journal_id = :t AND t.issn = s.issn)
            """),
            {"t": target_id, "s": source_id},
        )
        self._conn.execute(
            text("""
                UPDATE journal_issns
                SET journal_id = :t, sudoc_checked_at = NULL,
                    linking = linking AND NOT EXISTS (
                        SELECT 1 FROM journal_issns WHERE journal_id = :t AND linking
                    )
                WHERE journal_id = :s
            """),
            {"t": target_id, "s": source_id},
        )

        # Capture des métadonnées de la source, puis suppression de la source avant l'enrichissement : la cible reprend ensuite ses valeurs (COALESCE) sans conflit sur `UNIQUE(openalex_id)`.
        src = self._conn.execute(
            select(
                journals.c.publisher_id,
                journals.c.openalex_id,
                journals.c.is_in_doaj,
                journals.c.apc_amount,
                journals.c.apc_currency,
                journals.c.oa_model,
            ).where(journals.c.id == source_id)
        ).one()
        self._conn.execute(delete(journals).where(journals.c.id == source_id))
        self._conn.execute(
            update(journals)
            .where(journals.c.id == target_id)
            .values(
                publisher_id=func.coalesce(journals.c.publisher_id, src.publisher_id),
                openalex_id=func.coalesce(journals.c.openalex_id, src.openalex_id),
                is_in_doaj=journals.c.is_in_doaj | src.is_in_doaj,
                apc_amount=func.coalesce(journals.c.apc_amount, src.apc_amount),
                apc_currency=func.coalesce(journals.c.apc_currency, src.apc_currency),
                oa_model=func.coalesce(journals.c.oa_model, src.oa_model),
            )
        )

        # pub_count : la cible a absorbé les publications de la source. Recalcule la revue cible, puis les éditeurs concernés (cible + éditeur de la source).
        refresh_journal_pub_count(self._conn, target_id)
        target_publisher = self._conn.execute(
            select(journals.c.publisher_id).where(journals.c.id == target_id)
        ).scalar()
        for publisher_id in {target_publisher, src.publisher_id}:
            if publisher_id is not None:
                refresh_publisher_pub_count(self._conn, publisher_id)
