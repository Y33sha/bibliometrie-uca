"""Stats agrégées par laboratoire."""

from typing import Any

from infrastructure.db.queries.filters import (
    apply_oa_filter,
    apply_year_filter,
)
from infrastructure.db.queries.stats._shared import (
    apply_stats_apc_filter,
    paginated,
)

_LAB_SORT_MAP = {
    "name": "COALESCE(s.acronym, s.name) ASC",
    "-name": "COALESCE(s.acronym, s.name) DESC",
    "pubs": "COUNT(DISTINCT p.id) ASC",
    "-pubs": "COUNT(DISTINCT p.id) DESC",
    "apc": "apc_uca ASC NULLS FIRST",
    "-apc": "apc_uca DESC NULLS LAST",
}

_STRUCTS_CTE = """
    pub_structs AS (
        SELECT sd.publication_id, sa.structure_ids AS struct_ids
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.in_perimeter = TRUE AND sa.structure_ids IS NOT NULL
          AND sd.publication_id IS NOT NULL
    )
"""


def stats_labs(
    cur: Any,
    *,
    root_structure_id: int,
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
    page: int,
    per_page: int,
    sort: str,
) -> dict[str, Any]:
    """Stats agrégées par laboratoire, paginées."""
    offset = (page - 1) * per_page
    cur.execute("SET LOCAL jit = off")

    conditions = [
        "p.doc_type IN ('article', 'review')",
        "(j.oa_model IS DISTINCT FROM 'repository')",
    ]
    params: list[Any] = []
    if lab_ids:
        conditions.append("ps_structs.struct_ids && %s::int[]")
        params.append(lab_ids)
    apply_year_filter(conditions, params, years)
    if publisher_id:
        conditions.append("j.publisher_id = %s")
        params.append(publisher_id)
    if journal_id:
        conditions.append("p.journal_id = %s")
        params.append(journal_id)
    apply_oa_filter(conditions, params, oa_status)
    apply_stats_apc_filter(conditions, params, has_apc, root_structure_id)
    where = " AND ".join(conditions)

    cur.execute(
        f"""
        WITH {_STRUCTS_CTE}
        SELECT COUNT(DISTINCT s.id) AS total
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        JOIN pub_structs ps_structs ON ps_structs.publication_id = p.id
        JOIN structures s ON s.id = ANY(ps_structs.struct_ids) AND s.structure_type = 'labo'
        WHERE {where}
        """,
        params,
    )
    total = cur.fetchone()["total"]

    order = _LAB_SORT_MAP.get(sort, "COUNT(DISTINCT p.id) DESC")
    cur.execute(
        f"""
        WITH {_STRUCTS_CTE}
        SELECT
            s.id AS lab_id,
            s.acronym AS lab_acronym,
            s.name AS lab_name,
            COUNT(DISTINCT p.id) AS pub_count,
            COALESCE(SUM(DISTINCT ap_lab.amount_eur_ht), 0)::numeric(12,2) AS apc_uca,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'diamond') AS diamond,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        JOIN pub_structs ps_structs ON ps_structs.publication_id = p.id
        JOIN structures s ON s.id = ANY(ps_structs.struct_ids) AND s.structure_type = 'labo'
        LEFT JOIN apc_payments ap_lab ON ap_lab.publication_id = p.id AND ap_lab.lab_structure_id = s.id
        WHERE {where}
        GROUP BY s.id, s.acronym, s.name
        ORDER BY {order}
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    return paginated(total, page, per_page, "labs", cur.fetchall())
