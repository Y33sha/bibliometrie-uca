"""Query services pour les éditeurs (table `publishers`)."""

from typing import Any

from sqlalchemy import Connection, select, text

from application.ports.api.publishers_queries import (
    PublisherBasic,
    PublisherListItem,
    PublisherListResponse,
    PublisherQueries,
)
from infrastructure.db.tables import publishers as t_publishers

_SORT_MAP = {
    "name": "p.name ASC",
    "-name": "p.name DESC",
    "journals": "journal_count ASC, p.name ASC",
    "-journals": "journal_count DESC, p.name ASC",
    "pubs": "pub_count ASC, p.name ASC",
    "-pubs": "pub_count DESC, p.name ASC",
}


class PgPublisherQueries(PublisherQueries):
    """Adapter SA pour `application.ports.publishers_queries.PublisherQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_publishers(
        self, *, search: str | None, sort: str, page: int, per_page: int
    ) -> PublisherListResponse:
        binds: dict[str, Any] = {}
        where = "TRUE"
        if search and len(search) >= 2:
            where = "p.name_normalized LIKE '%' || :search || '%'"
            binds["search"] = search.lower()

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM publishers p WHERE {where}"),
            binds,
        ).one()
        total = total_row.total

        order = _SORT_MAP.get(sort, _SORT_MAP["name"])
        offset = (page - 1) * per_page
        rows = self._conn.execute(
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
        ).all()
        return PublisherListResponse(
            total=total,
            page=page,
            pages=(total + per_page - 1) // per_page,
            publishers=[
                PublisherListItem(
                    id=r.id,
                    name=r.name,
                    openalex_id=r.openalex_id,
                    country=r.country,
                    doi_prefix=r.doi_prefix,
                    is_predatory=r.is_predatory,
                    journal_count=r.journal_count,
                    pub_count=r.pub_count,
                )
                for r in rows
            ],
        )

    def get_publisher(self, publisher_id: int) -> PublisherBasic | None:
        row = self._conn.execute(
            text("SELECT id, name FROM publishers WHERE id = :id"),
            {"id": publisher_id},
        ).one_or_none()
        if row is None:
            return None
        return PublisherBasic(id=row.id, name=row.name)

    def existing_publisher_ids(self, publisher_ids: tuple[int, ...]) -> set[int]:
        if not publisher_ids:
            return set()
        result = self._conn.execute(
            select(t_publishers.c.id).where(t_publishers.c.id.in_(publisher_ids))
        )
        return {row.id for row in result}
