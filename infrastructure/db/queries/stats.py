"""Query services pour /api/stats/* (router pub_stats).

Extrait du router `interfaces/api/routers/pub_stats.py` pour respecter la
séparation des couches (§1.1) : le SQL vit dans infrastructure, le router
devient mince.

Contrat :
- Chaque fonction prend un curseur DB + les paramètres de filtre/pagination.
- Les agrégations APC utilisent le `root_structure_id` fourni par le caller
  (résolu en amont via la config — pas de dépendance FastAPI ici).
- Retourne des dicts ou listes Python natifs, sérialisables par FastAPI.
"""

from typing import Any

from infrastructure.db.queries.filters import (
    PUB_IS_UCA,
    apply_lab_filter,
    apply_oa_filter,
    apply_year_filter,
)

# Fragments APC — définis ici car spécifiques aux agrégations stats
# (distincts de apply_apc_filter qui filtre sur l'existence).
_APC_EXISTS = (
    "EXISTS (SELECT 1 FROM apc_payments ap "
    "WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s)"
)
_APC_NOT_EXISTS = (
    "NOT EXISTS (SELECT 1 FROM apc_payments ap "
    "WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s)"
)
_APC_SUM = """COALESCE((SELECT SUM(ap.amount_eur_ht)
     FROM apc_payments ap
     WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s
    ), 0)"""

_APC_FILTER_MAP = {
    "uca": (_APC_EXISTS, 1),
    "non_uca": (
        f"(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) "
        f"AND {_APC_NOT_EXISTS})",
        1,
    ),
    "none": (
        "NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)",
        0,
    ),
}


def _apply_stats_apc_filter(
    conditions: list, params: list, has_apc: str, root_structure_id: int
) -> None:
    """Filtre APC spécifique aux endpoints stats (supporte multi-sélection)."""
    if not has_apc:
        return
    values = [v.strip() for v in has_apc.split(",") if v.strip()]
    entries = [_APC_FILTER_MAP[v] for v in values if v in _APC_FILTER_MAP]
    parts = [e[0] for e in entries]
    for e in entries:
        params.extend([root_structure_id] * e[1])
    if len(parts) == 1:
        conditions.append(parts[0])
    elif len(parts) > 1:
        conditions.append("(" + " OR ".join(parts) + ")")


def _paginated(total: int, page: int, per_page: int, key: str, rows: list) -> dict[str, Any]:
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        key: rows,
    }


# ── Stats par éditeur ─────────────────────────────────────────────


_PUBLISHER_SORT_MAP = {
    "name": "pub.name ASC",
    "-name": "pub.name DESC",
    "pubs": "COUNT(DISTINCT p.id) ASC",
    "-pubs": "COUNT(DISTINCT p.id) DESC",
    "apc": "apc_uca ASC NULLS FIRST",
    "-apc": "apc_uca DESC NULLS LAST",
}


def publisher_stats(
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
    cur.execute("SET LOCAL jit = off")

    conditions = [
        PUB_IS_UCA,
        "p.doc_type IN ('article', 'review')",
        "j.oa_model IS DISTINCT FROM 'repository'",
    ]
    params: list[Any] = []
    apply_lab_filter(conditions, params, lab_ids)
    apply_year_filter(conditions, params, years)
    apply_oa_filter(conditions, params, oa_status)
    _apply_stats_apc_filter(conditions, params, has_apc, root_structure_id)
    if search:
        conditions.append("unaccent(pub.name) ILIKE unaccent(%s)")
        params.append(f"%{search}%")
    where = " AND ".join(conditions)

    cur.execute(
        f"""
        SELECT COUNT(DISTINCT pub.id) AS total
        FROM publications p
        JOIN journals j ON j.id = p.journal_id
        JOIN publishers pub ON pub.id = j.publisher_id
        WHERE {where}
        """,
        params,
    )
    total = cur.fetchone()["total"]

    order = _PUBLISHER_SORT_MAP.get(sort, "COUNT(DISTINCT p.id) DESC")
    cur.execute(
        f"""
        SELECT
            pub.id AS publisher_id,
            pub.name AS publisher_name,
            COUNT(DISTINCT j.id) AS journal_count,
            COUNT(DISTINCT p.id) AS pub_count,
            SUM({_APC_SUM})::numeric(12,2) AS apc_uca,
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
    return _paginated(total, page, per_page, "publishers", cur.fetchall())


# ── Stats par revue ───────────────────────────────────────────────


_JOURNAL_SORT_MAP = {
    "name": "j.title ASC",
    "-name": "j.title DESC",
    "pubs": "COUNT(DISTINCT p.id) ASC",
    "-pubs": "COUNT(DISTINCT p.id) DESC",
    "apc": "apc_uca ASC NULLS FIRST",
    "-apc": "apc_uca DESC NULLS LAST",
}


def journal_stats(
    cur: Any,
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
) -> dict[str, Any]:
    """Stats agrégées par revue, paginées."""
    offset = (page - 1) * per_page
    cur.execute("SET LOCAL jit = off")

    conditions = [
        PUB_IS_UCA,
        "j.id IS NOT NULL",
        "p.doc_type IN ('article', 'review')",
        "j.oa_model IS DISTINCT FROM 'repository'",
    ]
    params: list[Any] = []
    apply_lab_filter(conditions, params, lab_ids)
    apply_year_filter(conditions, params, years)
    if publisher_id:
        conditions.append("j.publisher_id = %s")
        params.append(publisher_id)
    if search:
        conditions.append("unaccent(j.title) ILIKE unaccent(%s)")
        params.append(f"%{search}%")
    apply_oa_filter(conditions, params, oa_status)
    _apply_stats_apc_filter(conditions, params, has_apc, root_structure_id)
    where = " AND ".join(conditions)

    cur.execute(
        f"""
        SELECT COUNT(DISTINCT j.id) AS total
        FROM publications p
        JOIN journals j ON j.id = p.journal_id
        WHERE {where}
        """,
        params,
    )
    total = cur.fetchone()["total"]

    order = _JOURNAL_SORT_MAP.get(sort, "COUNT(DISTINCT p.id) DESC")
    cur.execute(
        f"""
        SELECT
            j.id AS journal_id,
            j.title AS journal_title,
            j.issn,
            j.eissn,
            pub.name AS publisher_name,
            j.is_predatory,
            j.apc_amount,
            COUNT(DISTINCT p.id) AS pub_count,
            SUM({_APC_SUM})::numeric(12,2) AS apc_uca,
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
        LIMIT %s OFFSET %s
        """,
        [root_structure_id] + params + [per_page, offset],
    )
    return _paginated(total, page, per_page, "journals", cur.fetchall())


# ── Stats par année (graphiques) ──────────────────────────────────


def stats_by_year(
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
    cur.execute("SET LOCAL jit = off")

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
    _apply_stats_apc_filter(conditions, params, has_apc, root_structure_id)
    where = " AND ".join(conditions)

    cur.execute(
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
    return cur.fetchall()


# ── Résumé global ─────────────────────────────────────────────────


def stats_summary(
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
    cur.execute("SET LOCAL jit = off")

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
    _apply_stats_apc_filter(conditions, params, has_apc, root_structure_id)
    where = " AND ".join(conditions)

    cur.execute(
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
    return cur.fetchone()


# ── Stats par labo ────────────────────────────────────────────────


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
    _apply_stats_apc_filter(conditions, params, has_apc, root_structure_id)
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
    return _paginated(total, page, per_page, "labs", cur.fetchall())


# ── Années disponibles ────────────────────────────────────────────


def available_years(cur: Any) -> list[int]:
    """Liste des années de publication disponibles (périmètre UCA)."""
    cur.execute("SET LOCAL jit = off")
    cur.execute(f"""
        SELECT DISTINCT pub_year FROM publications p
        WHERE {PUB_IS_UCA} AND pub_year IS NOT NULL
        ORDER BY pub_year DESC
    """)
    return [r["pub_year"] for r in cur.fetchall()]


# ── Facettes croisées ────────────────────────────────────────────


def stats_facets(
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
    cur.execute("SET LOCAL jit = off")

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
            _apply_stats_apc_filter(conds, params, has_apc, root_structure_id)

    # --- ANNÉES ---
    year_conds = list(base_conditions)
    year_params: list[Any] = []
    add_common(year_conds, year_params, skip="year")
    cur.execute(
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
    year_facets = [{"value": r["pub_year"], "count": r["count"]} for r in cur.fetchall()]

    # --- LABOS ---
    lab_conds = list(base_conditions)
    lab_params: list[Any] = []
    add_common(lab_conds, lab_params, skip="lab")
    cur.execute(
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
        {"value": r["id"], "label": r["label"], "count": r["count"]} for r in cur.fetchall()
    ]

    # --- OA ---
    oa_conds = list(base_conditions)
    oa_params: list[Any] = []
    add_common(oa_conds, oa_params, skip="oa")
    cur.execute(
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
    oa_facets = [{"value": r["value"], "count": r["count"]} for r in cur.fetchall()]

    # --- APC ---
    apc_conds = list(base_conditions)
    apc_params: list[Any] = []
    add_common(apc_conds, apc_params, skip="apc")
    apc_where = " AND ".join(apc_conds) if apc_conds else "TRUE"
    cur.execute(
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
    ar = cur.fetchone()
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
