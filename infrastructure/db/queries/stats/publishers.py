"""Stats agrégées par éditeur (async)."""

from typing import Any

from infrastructure.db.queries.filters import (
    PUB_IS_UCA,
    apply_lab_filter,
    apply_oa_filter,
    apply_year_filter,
)
from infrastructure.db.queries.stats._shared import (
    APC_SUM,
    apply_stats_apc_filter,
    paginated,
)

_PUBLISHER_SORT_MAP = {
    "name": "pub.name ASC",
    "-name": "pub.name DESC",
    "pubs": "COUNT(DISTINCT p.id) ASC",
    "-pubs": "COUNT(DISTINCT p.id) DESC",
    "apc": "apc_uca ASC NULLS FIRST",
    "-apc": "apc_uca DESC NULLS LAST",
}


async def publisher_stats(
    cur: Any,
    *,
    root_structure_id: int,
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
    offset = (page - 1) * per_page
    await cur.execute("SET LOCAL jit = off")

    conditions = [
        PUB_IS_UCA,
        "p.doc_type IN ('article', 'review')",
        "j.oa_model IS DISTINCT FROM 'repository'",
    ]
    params: list[Any] = []
    apply_lab_filter(conditions, params, lab_ids)
    apply_year_filter(conditions, params, years)
    apply_oa_filter(conditions, params, oa_status)
    apply_stats_apc_filter(conditions, params, has_apc, root_structure_id)
    if search:
        conditions.append("unaccent(pub.name) ILIKE unaccent(%s)")
        params.append(f"%{search}%")
    where = " AND ".join(conditions)

    await cur.execute(
        f"""
        SELECT COUNT(DISTINCT pub.id) AS total
        FROM publications p
        JOIN journals j ON j.id = p.journal_id
        JOIN publishers pub ON pub.id = j.publisher_id
        WHERE {where}
        """,
        params,
    )
    row = await cur.fetchone()
    total = row["total"]

    order = _PUBLISHER_SORT_MAP.get(sort, "COUNT(DISTINCT p.id) DESC")
    await cur.execute(
        f"""
        SELECT
            pub.id AS publisher_id,
            pub.name AS publisher_name,
            COUNT(DISTINCT j.id) AS journal_count,
            COUNT(DISTINCT p.id) AS pub_count,
            SUM({APC_SUM})::numeric(12,2) AS apc_uca,
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
        LIMIT %s OFFSET %s
        """,
        [root_structure_id] + params + [per_page, offset],
    )
    return paginated(total, page, per_page, "publishers", await cur.fetchall())
