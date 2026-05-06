"""Adapter PostgreSQL async pour l'agrégat Publisher.

Parallèle à `publisher_repository.py` (sync). Séparé de
`async_journal_repository.py` (principe ISP).
"""

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.tables import publisher_name_forms, publishers


class PgAsyncPublisherRepository:
    """Accès PostgreSQL async à l'agrégat Publisher."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # ── publisher_name_forms ───────────────────────────────────────

    async def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
        stmt = (
            pg_insert(publisher_name_forms)
            .values(publisher_id=publisher_id, form_normalized=form_normalized)
            .on_conflict_do_nothing(index_elements=["form_normalized"])
        )
        await self._conn.execute(stmt)

    async def find_publisher_by_name_form(self, form_normalized: str) -> int | None:
        result = await self._conn.execute(
            select(publisher_name_forms.c.publisher_id)
            .where(publisher_name_forms.c.form_normalized == form_normalized)
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ── publishers ─────────────────────────────────────────────────

    async def find_publisher_by_openalex_id(self, openalex_id: str) -> int | None:
        result = await self._conn.execute(
            select(publishers.c.id).where(publishers.c.openalex_id == openalex_id)
        )
        return result.scalar_one_or_none()

    async def set_publisher_openalex_id_if_missing(
        self,
        publisher_id: int,
        openalex_id: str,
    ) -> None:
        stmt = (
            update(publishers)
            .where(publishers.c.id == publisher_id)
            .where(publishers.c.openalex_id.is_(None))
            .values(openalex_id=openalex_id)
        )
        await self._conn.execute(stmt)

    async def create_publisher(
        self,
        *,
        name: str,
        name_normalized: str,
        openalex_id: str | None,
    ) -> int:
        stmt = (
            publishers.insert()
            .values(name=name, name_normalized=name_normalized, openalex_id=openalex_id)
            .returning(publishers.c.id)
        )
        result = await self._conn.execute(stmt)
        return result.scalar_one()

    async def publisher_exists(self, publisher_id: int) -> bool:
        result = await self._conn.execute(
            select(publishers.c.id).where(publishers.c.id == publisher_id)
        )
        return result.first() is not None

    async def update_publisher_fields(self, publisher_id: int, fields: dict) -> None:
        stmt = (
            update(publishers)
            .where(publishers.c.id == publisher_id)
            .values(**fields, updated_at=func.now())
        )
        await self._conn.execute(stmt)

    # ── Fusion ─────────────────────────────────────────────────────

    async def merge_publisher_into(self, target_id: int, source_id: int) -> None:
        # 2. Transférer les journals restants
        await self._conn.execute(
            text("UPDATE journals SET publisher_id = :t WHERE publisher_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # 3. Transférer les publisher_name_forms (dédup sur form_normalized)
        await self._conn.execute(
            text("""
                UPDATE publisher_name_forms SET publisher_id = :t
                WHERE publisher_id = :s
                  AND form_normalized NOT IN (
                      SELECT form_normalized FROM publisher_name_forms
                      WHERE publisher_id = :t
                  )
            """),
            {"t": target_id, "s": source_id},
        )
        await self._conn.execute(
            delete(publisher_name_forms).where(publisher_name_forms.c.publisher_id == source_id)
        )

        # 3b. journal_name_forms (supprime d'abord les doublons avec target,
        # puis transfère le reste)
        await self._conn.execute(
            text("""
                DELETE FROM journal_name_forms
                WHERE publisher_id = :s
                  AND form_normalized IN (
                      SELECT form_normalized FROM journal_name_forms
                      WHERE publisher_id = :t
                  )
            """),
            {"t": target_id, "s": source_id},
        )
        await self._conn.execute(
            text("UPDATE journal_name_forms SET publisher_id = :t WHERE publisher_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # 4. Transférer les apc_payments
        await self._conn.execute(
            text("UPDATE apc_payments SET publisher_id = :t WHERE publisher_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # 5. Enrichir la cible (deux étapes : libérer l'openalex_id de la source,
        # puis le transférer si la cible n'en a pas).
        result = await self._conn.execute(
            select(publishers.c.openalex_id, publishers.c.country, publishers.c.is_predatory).where(
                publishers.c.id == source_id
            )
        )
        src = result.one()
        await self._conn.execute(
            update(publishers).where(publishers.c.id == source_id).values(openalex_id=None)
        )
        await self._conn.execute(
            update(publishers)
            .where(publishers.c.id == target_id)
            .values(
                openalex_id=func.coalesce(publishers.c.openalex_id, src.openalex_id),
                country=func.coalesce(publishers.c.country, src.country),
                is_predatory=publishers.c.is_predatory | src.is_predatory,
                updated_at=func.now(),
            )
        )

        # 6. Supprimer la source
        await self._conn.execute(delete(publishers).where(publishers.c.id == source_id))
