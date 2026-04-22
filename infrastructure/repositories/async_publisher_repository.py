"""Adapter PostgreSQL async pour l'agrégat Publisher (§2.12).

Parallèle à `publisher_repository.py`. Séparé de `async_journal_repository.py`
depuis §2.9.ISP.
"""

from typing import Any

from infrastructure.db_helpers import row_val as _val


class PgAsyncPublisherRepository:
    """Accès PostgreSQL async à l'agrégat Publisher."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    # ── publisher_name_forms ───────────────────────────────────────

    async def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
        await self._cur.execute(
            """
            INSERT INTO publisher_name_forms (publisher_id, form_normalized)
            VALUES (%s, %s)
            ON CONFLICT (form_normalized) DO NOTHING
            """,
            (publisher_id, form_normalized),
        )

    async def find_publisher_by_name_form(self, form_normalized: str) -> int | None:
        await self._cur.execute(
            """
            SELECT publisher_id FROM publisher_name_forms
            WHERE form_normalized = %s LIMIT 1
            """,
            (form_normalized,),
        )
        row = await self._cur.fetchone()
        return _val(row, 0) if row else None

    # ── publishers ─────────────────────────────────────────────────

    async def find_publisher_by_openalex_id(self, openalex_id: str) -> int | None:
        await self._cur.execute(
            "SELECT id FROM publishers WHERE openalex_id = %s",
            (openalex_id,),
        )
        row = await self._cur.fetchone()
        return _val(row, 0) if row else None

    async def set_publisher_openalex_id_if_missing(
        self,
        publisher_id: int,
        openalex_id: str,
    ) -> None:
        await self._cur.execute(
            """
            UPDATE publishers SET openalex_id = %s
            WHERE id = %s AND openalex_id IS NULL
            """,
            (openalex_id, publisher_id),
        )

    async def create_publisher(
        self,
        *,
        name: str,
        name_normalized: str,
        openalex_id: str | None,
    ) -> int:
        await self._cur.execute(
            """
            INSERT INTO publishers (name, name_normalized, openalex_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (name, name_normalized, openalex_id),
        )
        return _val(await self._cur.fetchone(), 0)

    async def publisher_exists(self, publisher_id: int) -> bool:
        await self._cur.execute("SELECT id FROM publishers WHERE id = %s", (publisher_id,))
        return (await self._cur.fetchone()) is not None

    async def update_publisher_fields(self, publisher_id: int, fields: dict) -> None:
        sets = ", ".join(f"{k} = %s" for k in fields)
        await self._cur.execute(
            f"UPDATE publishers SET {sets}, updated_at = now() WHERE id = %s",
            list(fields.values()) + [publisher_id],
        )

    # ── Fusion ─────────────────────────────────────────────────────

    async def merge_publisher_into(self, target_id: int, source_id: int) -> None:
        # 2. Transférer les journals restants
        await self._cur.execute(
            "UPDATE journals SET publisher_id = %s WHERE publisher_id = %s",
            (target_id, source_id),
        )

        # 3. Transférer les publisher_name_forms (dédup sur form_normalized)
        await self._cur.execute(
            """
            UPDATE publisher_name_forms SET publisher_id = %s
            WHERE publisher_id = %s
              AND form_normalized NOT IN (
                  SELECT form_normalized FROM publisher_name_forms WHERE publisher_id = %s
              )
            """,
            (target_id, source_id, target_id),
        )
        await self._cur.execute(
            "DELETE FROM publisher_name_forms WHERE publisher_id = %s",
            (source_id,),
        )

        # 3b. journal_name_forms (supprime d'abord les doublons avec target,
        # puis transfère le reste)
        await self._cur.execute(
            """
            DELETE FROM journal_name_forms
            WHERE publisher_id = %s
              AND form_normalized IN (
                  SELECT form_normalized FROM journal_name_forms WHERE publisher_id = %s
              )
            """,
            (source_id, target_id),
        )
        await self._cur.execute(
            "UPDATE journal_name_forms SET publisher_id = %s WHERE publisher_id = %s",
            (target_id, source_id),
        )

        # 4. Transférer les apc_payments
        await self._cur.execute(
            "UPDATE apc_payments SET publisher_id = %s WHERE publisher_id = %s",
            (target_id, source_id),
        )

        # 5. Enrichir la cible
        await self._cur.execute(
            "SELECT openalex_id, country, is_predatory FROM publishers WHERE id = %s",
            (source_id,),
        )
        src = await self._cur.fetchone()
        await self._cur.execute(
            "UPDATE publishers SET openalex_id = NULL WHERE id = %s",
            (source_id,),
        )
        await self._cur.execute(
            """
            UPDATE publishers SET
                openalex_id = COALESCE(openalex_id, %s),
                country = COALESCE(country, %s),
                is_predatory = is_predatory OR %s,
                updated_at = now()
            WHERE id = %s
            """,
            (src["openalex_id"], src["country"], src["is_predatory"], target_id),
        )

        # 6. Supprimer la source
        await self._cur.execute("DELETE FROM publishers WHERE id = %s", (source_id,))
