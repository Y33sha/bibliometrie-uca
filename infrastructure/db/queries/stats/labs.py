"""Stats agrégées par laboratoire."""

from typing import Any

from sqlalchemy import Connection, text

from infrastructure.db.queries.filters import (
    WhereClause,
    assemble_where,
    oa_clause,
    year_clause,
)
from infrastructure.db.queries.stats._shared import (
    paginated,
    stats_apc_clause,
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


def _build_stats_labs_sql(
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
) -> tuple[str, str, dict[str, Any]]:
    offset = (page - 1) * per_page
    static_clauses = " AND ".join(
        [
            "p.doc_type IN ('article', 'review')",
            "(j.oa_model IS DISTINCT FROM 'repository')",
        ]
    )
    # Spécificité de cet endpoint : lab filter sur ps_structs.struct_ids
    # (CTE) plutôt que sur authorships, donc lab_clause générique inadapté.
    lab_struct_clause = (
        WhereClause(
            "ps_structs.struct_ids && CAST(:flt_lab_ids AS int[])",
            {"flt_lab_ids": lab_ids},
        )
        if lab_ids
        else None
    )
    extra_clauses: list[WhereClause | None] = [
        lab_struct_clause,
        year_clause(years),
        oa_clause(oa_status),
        stats_apc_clause(has_apc, root_structure_id),
    ]
    if publisher_id:
        extra_clauses.append(
            WhereClause("j.publisher_id = :flt_publisher_id", {"flt_publisher_id": publisher_id})
        )
    if journal_id:
        extra_clauses.append(
            WhereClause("p.journal_id = :flt_journal_id", {"flt_journal_id": journal_id})
        )
    dyn_where, where_binds = assemble_where(extra_clauses)
    where = f"{static_clauses} AND {dyn_where}"

    count_sql = f"""
        WITH {_STRUCTS_CTE}
        SELECT COUNT(DISTINCT s.id) AS total
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        JOIN pub_structs ps_structs ON ps_structs.publication_id = p.id
        JOIN structures s ON s.id = ANY(ps_structs.struct_ids)
                         AND s.structure_type = 'labo'
        WHERE {where}
    """
    order = _LAB_SORT_MAP.get(sort, "COUNT(DISTINCT p.id) DESC")
    rows_sql = f"""
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
        JOIN structures s ON s.id = ANY(ps_structs.struct_ids)
                         AND s.structure_type = 'labo'
        LEFT JOIN apc_payments ap_lab
               ON ap_lab.publication_id = p.id AND ap_lab.lab_structure_id = s.id
        WHERE {where}
        GROUP BY s.id, s.acronym, s.name
        ORDER BY {order}
        LIMIT :pg_limit OFFSET :pg_offset
    """
    binds = {**where_binds, "pg_limit": per_page, "pg_offset": offset}
    return count_sql, rows_sql, binds


def stats_labs(conn: Connection, **kwargs: Any) -> dict[str, Any]:
    """Stats agrégées par laboratoire, paginées."""
    conn.execute(text("SET LOCAL jit = off"))
    count_sql, rows_sql, binds = _build_stats_labs_sql(**kwargs)
    total = conn.execute(text(count_sql), binds).one().total
    rows = conn.execute(text(rows_sql), binds).all()
    return paginated(
        total, kwargs["page"], kwargs["per_page"], "labs", [dict(r._mapping) for r in rows]
    )
