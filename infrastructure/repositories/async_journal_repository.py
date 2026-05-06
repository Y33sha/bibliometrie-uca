"""Adapter PostgreSQL async pour l'agrégat Journal.

L'agrégat Publisher est dans `async_publisher_repository.py` (principe ISP).
Parallèle à `journal_repository.py` (sync).
"""

from sqlalchemy import case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.tables import journal_name_forms, journals


class PgAsyncJournalRepository:
    """Accès PostgreSQL async à l'agrégat Journal."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # ── journal_name_forms ─────────────────────────────────────────

    async def add_journal_name_form(
        self,
        journal_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None:
        if not form_normalized:
            return
        stmt = (
            pg_insert(journal_name_forms)
            .values(
                journal_id=journal_id,
                form_normalized=form_normalized,
                publisher_id=publisher_id,
            )
            .on_conflict_do_nothing(index_elements=["form_normalized", "publisher_id"])
        )
        await self._conn.execute(stmt)

    async def find_journal_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None:
        # Tri pour préférer les journals avec eissn.
        stmt = (
            select(journal_name_forms.c.journal_id)
            .select_from(
                journal_name_forms.join(journals, journals.c.id == journal_name_forms.c.journal_id)
            )
            .where(journal_name_forms.c.form_normalized == form_normalized)
            .order_by(case((journals.c.eissn.is_not(None), 1), else_=0).desc(), journals.c.id.asc())
            .limit(1)
        )
        # Si publisher_id est fourni : match exact OU NULL ; sinon pas de
        # contrainte (toutes les rows match, le tri eissn>id départage).
        if publisher_id is not None:
            stmt = stmt.where(
                or_(
                    journal_name_forms.c.publisher_id == publisher_id,
                    journal_name_forms.c.publisher_id.is_(None),
                )
            )
        result = await self._conn.execute(stmt)
        return result.scalar_one_or_none()

    # ── journals ───────────────────────────────────────────────────

    async def find_journal_by_openalex_id(self, openalex_id: str) -> int | None:
        result = await self._conn.execute(
            select(journals.c.id).where(journals.c.openalex_id == openalex_id)
        )
        return result.scalar_one_or_none()

    async def find_journal_by_issn_any(self, issn_value: str) -> int | None:
        result = await self._conn.execute(
            select(journals.c.id)
            .where(
                or_(
                    journals.c.issn == issn_value,
                    journals.c.eissn == issn_value,
                    journals.c.issnl == issn_value,
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def enrich_journal(
        self,
        journal_id: int,
        *,
        issn: str | None = None,
        eissn: str | None = None,
        publisher_id: int | None = None,
        openalex_id: str | None = None,
        oa_model: str | None = None,
    ) -> None:
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                issn=func.coalesce(journals.c.issn, issn),
                eissn=func.coalesce(journals.c.eissn, eissn),
                publisher_id=func.coalesce(journals.c.publisher_id, publisher_id),
                openalex_id=func.coalesce(journals.c.openalex_id, openalex_id),
                oa_model=func.coalesce(journals.c.oa_model, oa_model),
            )
        )
        await self._conn.execute(stmt)

    async def create_journal(
        self,
        *,
        title: str,
        title_normalized: str,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        publisher_id: int | None,
        openalex_id: str | None,
        oa_model: str | None,
    ) -> int:
        stmt = (
            journals.insert()
            .values(
                title=title,
                title_normalized=title_normalized,
                issn=issn,
                eissn=eissn,
                issnl=issnl,
                publisher_id=publisher_id,
                openalex_id=openalex_id,
                oa_model=oa_model,
            )
            .returning(journals.c.id)
        )
        result = await self._conn.execute(stmt)
        return result.scalar_one()

    # ── Updates génériques ─────────────────────────────────────────

    async def journal_exists(self, journal_id: int) -> bool:
        result = await self._conn.execute(select(journals.c.id).where(journals.c.id == journal_id))
        return result.first() is not None

    async def update_journal_fields(self, journal_id: int, fields: dict) -> None:
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(**fields, updated_at=func.now())
        )
        await self._conn.execute(stmt)

    # ── APC / DOAJ ─────────────────────────────────────────────────

    async def update_journal_apc(
        self,
        journal_id: int,
        *,
        apc_amount: float | None = None,
        apc_currency: str | None = None,
        is_in_doaj: bool | None = None,
    ) -> None:
        stmt = (
            update(journals)
            .where(journals.c.id == journal_id)
            .values(
                apc_amount=func.coalesce(apc_amount, journals.c.apc_amount),
                apc_currency=func.coalesce(apc_currency, journals.c.apc_currency),
                is_in_doaj=func.coalesce(is_in_doaj, journals.c.is_in_doaj),
            )
        )
        await self._conn.execute(stmt)

    async def reset_journal_apc(self) -> int:
        stmt = (
            update(journals)
            .where(journals.c.openalex_id.is_not(None))
            .values(apc_amount=None, apc_currency="EUR", is_in_doaj=False)
        )
        result = await self._conn.execute(stmt)
        return result.rowcount

    # ── Fusion ─────────────────────────────────────────────────────

    async def find_shared_title_journal_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[dict]:
        jt = journals.alias("jt")
        js = journals.alias("js")
        stmt = (
            select(
                jt.c.id.label("target_journal_id"),
                js.c.id.label("source_journal_id"),
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
        result = await self._conn.execute(stmt)
        return [dict(r._mapping) for r in result]

    async def merge_journal_into(self, target_id: int, source_id: int) -> None:
        # 1. Transférer les publications et source_publications (cross-aggregate :
        #    on touche d'autres tables sans avoir migré leur MetaData ; SQL brut
        #    via text() — pattern documenté dans la fiche).
        await self._conn.execute(
            text("UPDATE publications SET journal_id = :t WHERE journal_id = :s"),
            {"t": target_id, "s": source_id},
        )
        await self._conn.execute(
            text("UPDATE source_publications SET journal_id = :t WHERE journal_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # 2. Transférer les journal_name_forms (anti-doublon)
        await self._conn.execute(
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
        await self._conn.execute(
            delete(journal_name_forms).where(journal_name_forms.c.journal_id == source_id)
        )

        # 3. Transférer les apc_payments (cross-aggregate)
        await self._conn.execute(
            text("UPDATE apc_payments SET journal_id = :t WHERE journal_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # 4. Enrichir la cible depuis la source (SELECT puis UPDATE pour
        # éviter le warning "cartesian product" sur UPDATE…FROM côté SA).
        src_result = await self._conn.execute(
            select(
                journals.c.issn,
                journals.c.eissn,
                journals.c.issnl,
                journals.c.publisher_id,
                journals.c.openalex_id,
                journals.c.is_in_doaj,
                journals.c.is_predatory,
                journals.c.apc_amount,
                journals.c.apc_currency,
                journals.c.oa_model,
            ).where(journals.c.id == source_id)
        )
        src = src_result.one()
        await self._conn.execute(
            update(journals)
            .where(journals.c.id == target_id)
            .values(
                issn=func.coalesce(journals.c.issn, src.issn),
                eissn=func.coalesce(journals.c.eissn, src.eissn),
                issnl=func.coalesce(journals.c.issnl, src.issnl),
                publisher_id=func.coalesce(journals.c.publisher_id, src.publisher_id),
                openalex_id=func.coalesce(journals.c.openalex_id, src.openalex_id),
                is_in_doaj=journals.c.is_in_doaj | src.is_in_doaj,
                is_predatory=journals.c.is_predatory | src.is_predatory,
                apc_amount=func.coalesce(journals.c.apc_amount, src.apc_amount),
                apc_currency=func.coalesce(journals.c.apc_currency, src.apc_currency),
                oa_model=func.coalesce(journals.c.oa_model, src.oa_model),
                updated_at=func.now(),
            )
        )

        # 5. Supprimer la source
        await self._conn.execute(delete(journals).where(journals.c.id == source_id))
