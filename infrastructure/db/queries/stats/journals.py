"""Stats agrégées par revue."""

from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.queries.filters import (
    PUB_IS_UCA,
    assemble_where,
    lab_clause,
    oa_clause,
    year_clause,
)
from infrastructure.db.queries.stats._shared import (
    APC_SUM_SA,
    paginated,
    stats_apc_clause,
)

_JOURNAL_SORT_MAP = {
    "name": "j.title ASC",
    "-name": "j.title DESC",
    "pubs": "COUNT(DISTINCT p.id) ASC",
    "-pubs": "COUNT(DISTINCT p.id) DESC",
    "apc": "apc_uca ASC NULLS FIRST",
    "-apc": "apc_uca DESC NULLS LAST",
}


def _build_journal_stats_sql(
    *,
    root_structure_id: int,
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    oa_status: str,
    has_apc: str,
    search: str,
    page: int,
    per_page: int,
    sort: str,
) -> tuple[str, str, dict[str, Any]]:
    """SQL count + rows + binds, partagé sync/async."""
    offset = (page - 1) * per_page
    static_clauses = " AND ".join(
        [
            PUB_IS_UCA,
            "j.id IS NOT NULL",
            "p.doc_type IN ('article', 'review')",
            "j.oa_model IS DISTINCT FROM 'repository'",
        ]
    )
    dyn_where, where_binds = assemble_where(
        [
            lab_clause(lab_ids),
            year_clause(years),
            oa_clause(oa_status),
            stats_apc_clause(has_apc, root_structure_id),
        ]
    )
    where = f"{static_clauses} AND {dyn_where}"
    if publisher_id:
        where += " AND j.publisher_id = :flt_publisher_id"
        where_binds["flt_publisher_id"] = publisher_id
    if search:
        where += " AND unaccent(j.title) ILIKE unaccent(:search_pat)"
        where_binds["search_pat"] = f"%{search}%"

    count_sql = f"""
        SELECT COUNT(DISTINCT j.id) AS total
        FROM publications p
        JOIN journals j ON j.id = p.journal_id
        WHERE {where}
    """
    order = _JOURNAL_SORT_MAP.get(sort, "COUNT(DISTINCT p.id) DESC")
    rows_sql = f"""
        SELECT
            j.id AS journal_id,
            j.title AS journal_title,
            j.issn,
            j.eissn,
            pub.name AS publisher_name,
            j.is_predatory,
            j.apc_amount,
            COUNT(DISTINCT p.id) AS pub_count,
            SUM({APC_SUM_SA})::numeric(12,2) AS apc_uca,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'diamond') AS diamond,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown
        FROM publications p
        JOIN journals j ON j.id = p.journal_id
        LEFT JOIN publishers pub ON pub.id = j.publisher_id
        WHERE {where}
        GROUP BY j.id, j.title, j.issn, j.eissn, pub.name, j.is_predatory, j.apc_amount
        ORDER BY {order}
        LIMIT :pg_limit OFFSET :pg_offset
    """
    binds = {
        **where_binds,
        "apc_root": root_structure_id,
        "pg_limit": per_page,
        "pg_offset": offset,
    }
    return count_sql, rows_sql, binds


async def journal_stats(conn: AsyncConnection, **kwargs: Any) -> dict[str, Any]:
    """Stats agrégées par revue, paginées (async)."""
    await conn.execute(text("SET LOCAL jit = off"))
    count_sql, rows_sql, binds = _build_journal_stats_sql(**kwargs)
    total = (await conn.execute(text(count_sql), binds)).one().total
    rows = (await conn.execute(text(rows_sql), binds)).all()
    return paginated(
        total, kwargs["page"], kwargs["per_page"], "journals", [dict(r._mapping) for r in rows]
    )


def journal_stats_sync(conn: Connection, **kwargs: Any) -> dict[str, Any]:
    """Stats agrégées par revue, paginées (sync)."""
    conn.execute(text("SET LOCAL jit = off"))
    count_sql, rows_sql, binds = _build_journal_stats_sql(**kwargs)
    total = conn.execute(text(count_sql), binds).one().total
    rows = conn.execute(text(rows_sql), binds).all()
    return paginated(
        total, kwargs["page"], kwargs["per_page"], "journals", [dict(r._mapping) for r in rows]
    )
