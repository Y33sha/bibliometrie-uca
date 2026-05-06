"""Query services pour les éditeurs (table `publishers`)."""

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.tables import publishers as t_publishers

_SORT_MAP = {
    "name": "p.name ASC",
    "-name": "p.name DESC",
    "journals": "journal_count ASC, p.name ASC",
    "-journals": "journal_count DESC, p.name ASC",
    "pubs": "pub_count ASC, p.name ASC",
    "-pubs": "pub_count DESC, p.name ASC",
}


class PgAsyncPublisherQueries:
    """Adapter SA pour `application.ports.publishers_queries.AsyncPublisherQueries`."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_publishers(
        self, *, search: str | None, sort: str, page: int, per_page: int
    ) -> dict[str, Any]:
        binds: dict[str, Any] = {}
        where = "TRUE"
        if search and len(search) >= 2:
            where = "p.name_normalized LIKE '%' || :search || '%'"
            binds["search"] = search.lower()

        total_row = (
            await self._conn.execute(
                text(f"SELECT COUNT(*) AS total FROM publishers p WHERE {where}"),
                binds,
            )
        ).one()
        total = total_row.total

        order = _SORT_MAP.get(sort, _SORT_MAP["name"])
        offset = (page - 1) * per_page
        rows = (
            await self._conn.execute(
                text(f"""
                    SELECT p.id, p.name, p.openalex_id, p.country,
                           p.doi_prefix, p.is_predatory,
                           (SELECT COUNT(*) FROM journals j
                            WHERE j.publisher_id = p.id) AS journal_count,
                           (SELECT COUNT(*) FROM publications pub
                            JOIN journals j2 ON j2.id = pub.journal_id
                            WHERE j2.publisher_id = p.id) AS pub_count
                    FROM publishers p
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
            "publishers": [dict(r._mapping) for r in rows],
        }

    async def get_publisher(self, publisher_id: int) -> dict[str, Any] | None:
        row = (
            await self._conn.execute(
                text("SELECT id, name FROM publishers WHERE id = :id"),
                {"id": publisher_id},
            )
        ).one_or_none()
        return dict(row._mapping) if row else None

    async def existing_publisher_ids(self, publisher_ids: tuple[int, ...]) -> set[int]:
        if not publisher_ids:
            return set()
        result = await self._conn.execute(
            select(t_publishers.c.id).where(t_publishers.c.id.in_(publisher_ids))
        )
        return {row.id for row in result}
