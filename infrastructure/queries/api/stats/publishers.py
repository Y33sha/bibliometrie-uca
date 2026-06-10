"""Stats agrégées par éditeur."""

from typing import Any

from sqlalchemy import Connection, text

from infrastructure.queries.api.stats._shared import (
    APC_SUM_SA,
    paginated,
    stats_apc_clause,
)
from infrastructure.queries.filters import (
    PUBLICATION_IS_IN_PERIMETER,
    assemble_where,
    lab_clause,
    oa_clause,
    year_clause,
)

_PUBLISHER_SORT_MAP = {
    "name": "pub.name ASC",
    "-name": "pub.name DESC",
    "pubs": "COUNT(DISTINCT p.id) ASC",
    "-pubs": "COUNT(DISTINCT p.id) DESC",
    "apc": "apc_uca ASC NULLS FIRST",
    "-apc": "apc_uca DESC NULLS LAST",
}


def _build_publisher_stats_sql(
    *,
    apc_structure_ids: list[int],
    lab_ids: list[int],
    years: list[int],
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
            PUBLICATION_IS_IN_PERIMETER,
            "p.doc_type IN ('article', 'review')",
            "j.oa_model IS DISTINCT FROM 'repository'",
        ]
    )
    dyn_where, where_binds = assemble_where(
        [
            lab_clause(lab_ids),
            year_clause(years),
            oa_clause(oa_status),
            stats_apc_clause(has_apc, apc_structure_ids),
        ]
    )
    where = f"{static_clauses} AND {dyn_where}"
    if search:
        where += " AND unaccent(pub.name) ILIKE unaccent(:search_pat)"
        where_binds["search_pat"] = f"%{search}%"

    count_sql = f"""
        SELECT COUNT(DISTINCT pub.id) AS total
        FROM publications p
        JOIN journals j ON j.id = p.journal_id
        JOIN publishers pub ON pub.id = j.publisher_id
        WHERE {where}
    """
    order = _PUBLISHER_SORT_MAP.get(sort, "COUNT(DISTINCT p.id) DESC")
    rows_sql = f"""
        SELECT
            pub.id AS publisher_id,
            pub.name AS publisher_name,
            COUNT(DISTINCT j.id) AS journal_count,
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
        JOIN publishers pub ON pub.id = j.publisher_id
        WHERE {where}
        GROUP BY pub.id, pub.name
        ORDER BY {order}
        LIMIT :pg_limit OFFSET :pg_offset
    """
    binds = {
        **where_binds,
        "apc_root_ids": apc_structure_ids,
        "pg_limit": per_page,
        "pg_offset": offset,
    }
    return count_sql, rows_sql, binds


def publisher_stats(
    conn: Connection,
    *,
    apc_structure_ids: list[int],
    lab_ids: list[int],
    years: list[int],
    oa_status: str,
    has_apc: str,
    search: str,
    page: int,
    per_page: int,
    sort: str,
) -> dict[str, Any]:
    """Stats agrégées par éditeur, paginées."""
    conn.execute(text("SET LOCAL jit = off"))
    count_sql, rows_sql, binds = _build_publisher_stats_sql(
        apc_structure_ids=apc_structure_ids,
        lab_ids=lab_ids,
        years=years,
        oa_status=oa_status,
        has_apc=has_apc,
        search=search,
        page=page,
        per_page=per_page,
        sort=sort,
    )
    total = conn.execute(text(count_sql), binds).one().total
    rows = conn.execute(text(rows_sql), binds).all()
    return paginated(total, page, per_page, "publishers", [dict(r._mapping) for r in rows])
