"""Résumé global, ventilation annuelle, années disponibles, facettes croisées (§2.12 : async)."""

from typing import Any

from infrastructure.db.queries.filters import (
    PUB_IS_UCA,
    apply_lab_filter,
    apply_oa_filter,
    apply_year_filter,
)
from infrastructure.db.queries.stats._shared import apply_stats_apc_filter


async def stats_by_year(
    cur: Any,
    *,
    root_structure_id: int,
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
) -> list[dict[str, Any]]:
    """Ventilation par année (articles + review, périmètre UCA)."""
    await cur.execute("SET LOCAL jit = off")

    conditions = [
        PUB_IS_UCA,
        "p.doc_type IN ('article', 'review')",
        "(j.oa_model IS DISTINCT FROM 'repository')",
    ]
    params: list[Any] = []
    apply_lab_filter(conditions, params, lab_ids)
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

    await cur.execute(
        f"""
        SELECT
            p.pub_year,
            COUNT(DISTINCT p.id) AS pub_count,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'diamond') AS diamond,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {where}
        GROUP BY p.pub_year
        ORDER BY p.pub_year
        """,
        params,
    )
    return await cur.fetchall()


async def stats_summary(
    cur: Any,
    *,
    root_structure_id: int,
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
) -> dict[str, Any]:
    """Totaux globaux pour la page stats."""
    await cur.execute("SET LOCAL jit = off")

    conditions = [
        PUB_IS_UCA,
        "p.doc_type IN ('article', 'review')",
        "(j.oa_model IS DISTINCT FROM 'repository')",
    ]
    params: list[Any] = []
    apply_lab_filter(conditions, params, lab_ids)
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

    await cur.execute(
        f"""
        SELECT
            COUNT(DISTINCT p.id) AS total_pubs,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown,
            COUNT(DISTINCT j.publisher_id) AS publisher_count,
            COUNT(DISTINCT j.id) AS journal_count
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {where}
        """,
        params,
    )
    return await cur.fetchone()


async def available_years(cur: Any) -> list[int]:
    """Liste des années de publication disponibles (périmètre UCA)."""
    await cur.execute("SET LOCAL jit = off")
    await cur.execute(f"""
        SELECT DISTINCT pub_year FROM publications p
        WHERE {PUB_IS_UCA} AND pub_year IS NOT NULL
        ORDER BY pub_year DESC
    """)
    return [r["pub_year"] for r in await cur.fetchall()]


async def stats_facets(
    cur: Any,
    *,
    root_structure_id: int,
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
) -> dict[str, list[dict[str, Any]]]:
    """Facettes dynamiques (années, labos, oa_status, apc) : chaque facette
    exclut son propre filtre mais applique tous les autres."""
    await cur.execute("SET LOCAL jit = off")

    base_conditions = [
        PUB_IS_UCA,
        "p.doc_type IN ('article', 'review')",
        "(j.oa_model IS DISTINCT FROM 'repository')",
    ]

    def add_common(conds: list, params: list, *, skip: str) -> None:
        if skip != "year":
            apply_year_filter(conds, params, years)
        if skip != "lab":
            apply_lab_filter(conds, params, lab_ids)
        if publisher_id:
            conds.append("j.publisher_id = %s")
            params.append(publisher_id)
        if journal_id:
            conds.append("p.journal_id = %s")
            params.append(journal_id)
        if skip != "oa":
            apply_oa_filter(conds, params, oa_status)
        if skip != "apc":
            apply_stats_apc_filter(conds, params, has_apc, root_structure_id)

    # --- ANNÉES ---
    year_conds = list(base_conditions)
    year_params: list[Any] = []
    add_common(year_conds, year_params, skip="year")
    await cur.execute(
        f"""
        SELECT p.pub_year, COUNT(DISTINCT p.id) AS count
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {" AND ".join(year_conds)}
          AND p.pub_year IS NOT NULL
        GROUP BY p.pub_year
        ORDER BY p.pub_year DESC
        """,
        year_params,
    )
    year_facets = [{"value": r["pub_year"], "count": r["count"]} for r in await cur.fetchall()]

    # --- LABOS ---
    lab_conds = list(base_conditions)
    lab_params: list[Any] = []
    add_common(lab_conds, lab_params, skip="lab")
    await cur.execute(
        f"""
        SELECT s.id, COALESCE(s.acronym, s.name) AS label,
               COUNT(DISTINCT a.publication_id) AS count
        FROM authorships a
        JOIN publications p ON p.id = a.publication_id
        LEFT JOIN journals j ON j.id = p.journal_id
        CROSS JOIN LATERAL unnest(a.structure_ids) AS struct_id
        JOIN structures s ON s.id = struct_id
        WHERE {" AND ".join(lab_conds)}
          AND s.structure_type = 'labo'
        GROUP BY s.id, s.acronym, s.name
        ORDER BY count DESC
        """,
        lab_params,
    )
    lab_facets = [
        {"value": r["id"], "label": r["label"], "count": r["count"]} for r in await cur.fetchall()
    ]

    # --- OA ---
    oa_conds = list(base_conditions)
    oa_params: list[Any] = []
    add_common(oa_conds, oa_params, skip="oa")
    await cur.execute(
        f"""
        SELECT p.oa_status::text AS value, COUNT(DISTINCT p.id) AS count
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {" AND ".join(oa_conds)}
          AND p.oa_status IS NOT NULL
        GROUP BY p.oa_status
        ORDER BY count DESC
        """,
        oa_params,
    )
    oa_facets = [{"value": r["value"], "count": r["count"]} for r in await cur.fetchall()]

    # --- APC ---
    apc_conds = list(base_conditions)
    apc_params: list[Any] = []
    add_common(apc_conds, apc_params, skip="apc")
    apc_where = " AND ".join(apc_conds) if apc_conds else "TRUE"
    await cur.execute(
        f"""
        SELECT
            COUNT(DISTINCT p.id) FILTER (WHERE EXISTS (
                SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s
            )) AS apc_uca,
            COUNT(DISTINCT p.id) FILTER (WHERE EXISTS (
                SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
            ) AND NOT EXISTS (
                SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s
            )) AS apc_non_uca,
            COUNT(DISTINCT p.id) FILTER (WHERE NOT EXISTS (
                SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
            )) AS apc_none
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id
        WHERE {apc_where}
        """,
        [root_structure_id, root_structure_id] + apc_params,
    )
    ar = await cur.fetchone()
    apc_facets = [
        {"value": "uca", "text": "APC UCA", "count": ar["apc_uca"]},
        {"value": "non_uca", "text": "APC hors UCA", "count": ar["apc_non_uca"]},
        {"value": "none", "text": "Sans APC", "count": ar["apc_none"]},
    ]

    return {
        "years": year_facets,
        "labs": lab_facets,
        "oa_statuses": oa_facets,
        "apc": apc_facets,
    }
