"""Query services pour les revues (table `journals`)."""

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.tables import journals as t_journals

_SORT_MAP = {
    "title": "j.title ASC",
    "-title": "j.title DESC",
    "publisher": "pub_name ASC NULLS LAST, j.title ASC",
    "-publisher": "pub_name DESC NULLS LAST, j.title ASC",
    "pubs": "pub_count ASC, j.title ASC",
    "-pubs": "pub_count DESC, j.title ASC",
}


class PgAsyncJournalQueries:
    """Adapter SA pour `application.ports.journals_queries.AsyncJournalQueries`."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_journals(
        self,
        *,
        search: str | None,
        publisher_id: int | None,
        sort: str,
        page: int,
        per_page: int,
    ) -> dict[str, Any]:
        binds: dict[str, Any] = {}
        parts: list[str] = []
        if search and len(search) >= 2:
            parts.append("j.title_normalized LIKE '%' || :search || '%'")
            binds["search"] = search.lower()
        if publisher_id:
            parts.append("j.publisher_id = :publisher_id")
            binds["publisher_id"] = publisher_id
        where = " AND ".join(parts) if parts else "TRUE"

        total_row = (
            await self._conn.execute(
                text(f"SELECT COUNT(*) AS total FROM journals j WHERE {where}"),
                binds,
            )
        ).one()
        total = total_row.total

        order = _SORT_MAP.get(sort, _SORT_MAP["title"])
        offset = (page - 1) * per_page
        rows = (
            await self._conn.execute(
                text(f"""
                    SELECT j.id, j.title, j.issn, j.eissn, j.issnl,
                           j.publisher_id, p.name AS pub_name,
                           j.openalex_id, j.is_in_doaj, j.is_predatory,
                           j.apc_amount, j.apc_currency, j.oa_model,
                           j.journal_type, j.is_academic, j.doi_prefix, j.notes,
                           (SELECT COUNT(*) FROM publications pub
                            WHERE pub.journal_id = j.id) AS pub_count
                    FROM journals j
                    LEFT JOIN publishers p ON p.id = j.publisher_id
                    WHERE {where}
                    ORDER BY {order}
                    LIMIT :pg_limit OFFSET :pg_offset
                """),
                {**binds, "pg_limit": per_page, "pg_offset": offset},
            )
        ).all()
        return {
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
            "journals": [dict(r._mapping) for r in rows],
        }

    async def get_journal(self, journal_id: int) -> dict[str, Any] | None:
        row = (
            await self._conn.execute(
                text("SELECT id, title FROM journals WHERE id = :id"),
                {"id": journal_id},
            )
        ).one_or_none()
        return dict(row._mapping) if row else None

    async def existing_journal_ids(self, journal_ids: tuple[int, ...]) -> set[int]:
        if not journal_ids:
            return set()
        result = await self._conn.execute(
            select(t_journals.c.id).where(t_journals.c.id.in_(journal_ids))
        )
        return {row.id for row in result}
