"""Adapter PostgreSQL pour l'édition et la fusion curées de l'agrégat Journal.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP). Le trouve-ou-crée et l'enrichissement, alimentés par le pipeline, vivent dans `infrastructure/pipeline/journals.py`.

Même contrat que les autres PgXxxRepository : exceptions du domaine, l'orchestration métier restant dans `application/services/journals/`.
"""

from typing import Any

from sqlalchemy import Connection, delete, func, select, text, update

from application.ports.repositories.journal_repository import (
    JournalRepository,
    JournalUpdate,
)
from domain.errors import NotFoundError
from domain.journals.journal import JournalType
from domain.normalize import normalize_text
from infrastructure.db.tables import journal_name_forms, journals
from infrastructure.pipeline.authorships.pub_counts import (
    refresh_journal_pub_count,
    refresh_publisher_pub_count,
)


class PgJournalRepository(JournalRepository):
    """Accès PostgreSQL à l'agrégat Journal via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Lectures de commande ───────────────────────────────────────

    def exists(self, journal_id: int) -> bool:
        return (
            self._conn.execute(select(journals.c.id).where(journals.c.id == journal_id)).first()
            is not None
        )

    def get_journal_type(self, journal_id: int) -> JournalType | None:
        row = self._conn.execute(
            select(journals.c.journal_type).where(journals.c.id == journal_id)
        ).first()
        if row is None:
            return None
        return JournalType(row[0]) if row[0] is not None else JournalType.UNKNOWN

    # ── Édition sélective ──────────────────────────────────────────

    def update_journal_fields(self, journal_id: int, fields: JournalUpdate) -> None:
        data = fields.model_dump(exclude_unset=True)
        if data.get("title") is not None:
            data["title_normalized"] = normalize_text(data["title"])
        stmt = update(journals).where(journals.c.id == journal_id).values(**data)
        result = self._conn.execute(stmt)
        if result.rowcount == 0:
            raise NotFoundError(f"Revue {journal_id} introuvable")

    # ── Fusion ─────────────────────────────────────────────────────

    def find_shared_title_journal_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[dict[str, Any]]:
        jt = journals.alias("jt")
        js = journals.alias("js")
        stmt = (
            select(
                jt.c.id.label("target_journal_id"),
                js.c.id.label("source_journal_id"),
                jt.c.title.label("t_title"),
                js.c.title.label("s_title"),
                jt.c.issn.label("t_issn"),
                jt.c.eissn.label("t_eissn"),
                jt.c.issnl.label("t_issnl"),
                js.c.issn.label("s_issn"),
                js.c.eissn.label("s_eissn"),
                js.c.issnl.label("s_issnl"),
            )
            .select_from(jt.join(js, js.c.title_normalized == jt.c.title_normalized))
            .where(jt.c.publisher_id == target_publisher_id)
            .where(js.c.publisher_id == source_publisher_id)
        )
        return [dict(r._mapping) for r in self._conn.execute(stmt)]

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

        # Capture des métadonnées de la source, puis suppression de la source avant l'enrichissement : la cible reprend ensuite ses valeurs (COALESCE) sans conflit sur `UNIQUE(openalex_id)`.
        src = self._conn.execute(
            select(
                journals.c.issn,
                journals.c.eissn,
                journals.c.issnl,
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
                issn=func.coalesce(journals.c.issn, src.issn),
                eissn=func.coalesce(journals.c.eissn, src.eissn),
                issnl=func.coalesce(journals.c.issnl, src.issnl),
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
        for publisher_id in {target_publisher, src.publisher_id} - {None}:
            refresh_publisher_pub_count(self._conn, publisher_id)
