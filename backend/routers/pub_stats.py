"""Auto-extracted router."""

from fastapi import APIRouter, Query
from backend.deps import get_cursor
from backend.filters import (PUB_IS_UCA, parse_int_csv,
    apply_lab_filter, apply_year_filter, apply_oa_filter)

router = APIRouter()

# UCA structure id
UCA_STRUCT_ID = 169

# APC sum subquery (UCA budget only)
APC_UCA_SUM = """
    COALESCE((SELECT SUM(ap.amount_eur_ht)
     FROM apc_payments ap
     WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169
    ), 0)
"""


APC_SQL = {
    "uca": "EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169)",
    "non_uca": "(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) AND NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169))",
    "none": "NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)",
}


def apply_apc_filter(conditions: list, has_apc: str):
    """Ajoute le filtre APC aux conditions SQL. Supporte multi-sélection (virgule)."""
    if not has_apc:
        return
    values = [v.strip() for v in has_apc.split(',') if v.strip()]
    parts = [APC_SQL[v] for v in values if v in APC_SQL]
    if len(parts) == 1:
        conditions.append(parts[0])
    elif len(parts) > 1:
        conditions.append("(" + " OR ".join(parts) + ")")


@router.get("/api/pub-stats/publishers")
async def publisher_stats(
    lab_id: str = Query(""),
    year: str = Query(""),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    sort: str = Query("-pubs"),
):
    """Stats d'articles par éditeur."""
    offset = (page - 1) * per_page
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            PUB_IS_UCA,
            "p.doc_type IN ('article', 'review')",
            "j.oa_model IS DISTINCT FROM 'repository'",
        ]
        params = []

        apply_lab_filter(conditions, params, lab_ids)
        apply_year_filter(conditions, params, years)
        apply_oa_filter(conditions, params, oa_status)
        apply_apc_filter(conditions, has_apc)

        if search:
            conditions.append("unaccent(pub.name) ILIKE unaccent(%s)")
            params.append(f"%{search}%")

        where = " AND ".join(conditions)

        cur.execute(f"""
            SELECT COUNT(DISTINCT pub.id) AS total
            FROM publications p
            JOIN journals j ON j.id = p.journal_id
            JOIN publishers pub ON pub.id = j.publisher_id
            WHERE {where}
        """, params)
        total = cur.fetchone()["total"]

        cur.execute(f"""
            SELECT
                pub.id AS publisher_id,
                pub.name AS publisher_name,
                COUNT(DISTINCT j.id) AS journal_count,
                COUNT(DISTINCT p.id) AS pub_count,
                SUM({APC_UCA_SUM})::numeric(12,2) AS apc_uca,
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
            ORDER BY {
                {
                    "name": "pub.name ASC",
                    "-name": "pub.name DESC",
                    "pubs": "COUNT(DISTINCT p.id) ASC",
                    "-pubs": "COUNT(DISTINCT p.id) DESC",
                }.get(sort, "COUNT(DISTINCT p.id) DESC")
            }
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "publishers": cur.fetchall(),
        }


@router.get("/api/pub-stats/journals")
async def journal_stats(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    sort: str = Query("-pubs"),
):
    """Stats d'articles par revue."""
    offset = (page - 1) * per_page
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            PUB_IS_UCA,
            "j.id IS NOT NULL",
            "p.doc_type IN ('article', 'review')",
            "j.oa_model IS DISTINCT FROM 'repository'",
        ]
        params = []

        apply_lab_filter(conditions, params, lab_ids)
        apply_year_filter(conditions, params, years)

        if publisher_id:
            conditions.append("j.publisher_id = %s")
            params.append(publisher_id)

        if search:
            conditions.append("unaccent(j.title) ILIKE unaccent(%s)")
            params.append(f"%{search}%")

        apply_oa_filter(conditions, params, oa_status)
        apply_apc_filter(conditions, has_apc)

        where = " AND ".join(conditions)

        cur.execute(f"""
            SELECT COUNT(DISTINCT j.id) AS total
            FROM publications p
            JOIN journals j ON j.id = p.journal_id
            WHERE {where}
        """, params)
        total = cur.fetchone()["total"]

        cur.execute(f"""
            SELECT
                j.id AS journal_id,
                j.title AS journal_title,
                j.issn,
                j.eissn,
                pub.name AS publisher_name,
                j.is_predatory,
                j.apc_amount,
                COUNT(DISTINCT p.id) AS pub_count,
                SUM({APC_UCA_SUM})::numeric(12,2) AS apc_uca,
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
            ORDER BY {
                {
                    "name": "j.title ASC",
                    "-name": "j.title DESC",
                    "pubs": "COUNT(DISTINCT p.id) ASC",
                    "-pubs": "COUNT(DISTINCT p.id) DESC",
                }.get(sort, "COUNT(DISTINCT p.id) DESC")
            }
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "journals": cur.fetchall(),
        }


@router.get("/api/pub-stats/by-year")
async def stats_by_year(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
):
    """Ventilation par année (pour les graphiques)."""
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            PUB_IS_UCA,
            "p.doc_type IN ('article', 'review')",
            "(j.oa_model IS DISTINCT FROM 'repository')",
        ]
        params = []

        apply_lab_filter(conditions, params, lab_ids)
        apply_year_filter(conditions, params, years)

        if publisher_id:
            conditions.append("j.publisher_id = %s")
            params.append(publisher_id)

        if journal_id:
            conditions.append("p.journal_id = %s")
            params.append(journal_id)

        apply_oa_filter(conditions, params, oa_status)
        apply_apc_filter(conditions, has_apc)

        where = " AND ".join(conditions)

        cur.execute(f"""
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
        """, params)

        return cur.fetchall()


@router.get("/api/pub-stats/summary")
async def stats_summary(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
):
    """Résumé global."""
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            PUB_IS_UCA,
            "p.doc_type IN ('article', 'review')",
            "(j.oa_model IS DISTINCT FROM 'repository')",
        ]
        params = []

        apply_lab_filter(conditions, params, lab_ids)
        apply_year_filter(conditions, params, years)

        if publisher_id:
            conditions.append("j.publisher_id = %s")
            params.append(publisher_id)

        if journal_id:
            conditions.append("p.journal_id = %s")
            params.append(journal_id)

        apply_oa_filter(conditions, params, oa_status)
        apply_apc_filter(conditions, has_apc)

        where = " AND ".join(conditions)

        cur.execute(f"""
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
        """, params)

        return cur.fetchone()


@router.get("/api/pub-stats/labs")
async def stats_labs(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    sort: str = Query("-pubs"),
):
    """Stats d'articles par laboratoire."""
    offset = (page - 1) * per_page
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        conditions = [
            "p.doc_type IN ('article', 'review')",
            "(j.oa_model IS DISTINCT FROM 'repository')",
        ]
        params = []

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
        apply_apc_filter(conditions, has_apc)

        where = " AND ".join(conditions)

        # CTE: union des structure_ids UCA depuis les authorships sources
        structs_cte = """
            pub_structs AS (
                SELECT sd.publication_id, sa.structure_ids AS struct_ids
                FROM source_authorships sa
                JOIN source_documents sd ON sd.id = sa.source_document_id
                WHERE sa.in_perimeter = TRUE AND sa.structure_ids IS NOT NULL
                  AND sd.publication_id IS NOT NULL
            )
        """

        cur.execute(f"""
            WITH {structs_cte}
            SELECT COUNT(DISTINCT s.id) AS total
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            JOIN pub_structs ps_structs ON ps_structs.publication_id = p.id
            JOIN structures s ON s.id = ANY(ps_structs.struct_ids) AND s.structure_type = 'labo'
            WHERE {where}
        """, params)
        total = cur.fetchone()["total"]

        cur.execute(f"""
            WITH {structs_cte}
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
            ORDER BY {
                {
                    "name": "COALESCE(s.acronym, s.name) ASC",
                    "-name": "COALESCE(s.acronym, s.name) DESC",
                    "pubs": "COUNT(DISTINCT p.id) ASC",
                    "-pubs": "COUNT(DISTINCT p.id) DESC",
                }.get(sort, "COUNT(DISTINCT p.id) DESC")
            }
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "labs": cur.fetchall(),
        }


@router.get("/api/pub-stats/years")
async def available_years():
    """Années disponibles (validées uniquement)."""
    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        cur.execute(f"""
            SELECT DISTINCT pub_year FROM publications p
            WHERE {PUB_IS_UCA} AND pub_year IS NOT NULL
            ORDER BY pub_year DESC
        """)
        return [r["pub_year"] for r in cur.fetchall()]


@router.get("/api/pub-stats/facets")
async def stats_facets(
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    has_apc: str = Query(""),
):
    """Facettes dynamiques : retourne les années et labos disponibles
    en tenant compte des filtres croisés (chaque facette exclut son propre filtre)."""
    lab_ids = parse_int_csv(lab_id)
    years = parse_int_csv(year)

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")

        # Conditions de base (communes à toutes les facettes)
        base_conditions = [
            PUB_IS_UCA,
            "p.doc_type IN ('article', 'review')",
            "(j.oa_model IS DISTINCT FROM 'repository')",
        ]

        def add_common(conds, params, *, skip: str):
            """Ajoute tous les filtres sauf celui indiqué."""
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
                apply_apc_filter(conds, has_apc)

        # --- Facette ANNÉES (exclut le filtre année, garde les autres) ---
        year_conds = list(base_conditions)
        year_params: list = []
        add_common(year_conds, year_params, skip="year")

        cur.execute(f"""
            SELECT p.pub_year, COUNT(DISTINCT p.id) AS count
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            WHERE {" AND ".join(year_conds)}
              AND p.pub_year IS NOT NULL
            GROUP BY p.pub_year
            ORDER BY p.pub_year DESC
        """, year_params)
        year_facets = [{"value": r["pub_year"], "count": r["count"]}
                       for r in cur.fetchall()]

        # --- Facette LABOS (exclut le filtre labo, garde les autres) ---
        lab_conds = list(base_conditions)
        lab_params: list = []
        add_common(lab_conds, lab_params, skip="lab")

        cur.execute(f"""
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
        """, lab_params)
        lab_facets = [{"value": r["id"], "label": r["label"], "count": r["count"]}
                      for r in cur.fetchall()]

        # --- Facette OA (exclut le filtre OA, garde les autres) ---
        oa_conds = list(base_conditions)
        oa_params: list = []
        add_common(oa_conds, oa_params, skip="oa")

        cur.execute(f"""
            SELECT p.oa_status::text AS value, COUNT(DISTINCT p.id) AS count
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            WHERE {" AND ".join(oa_conds)}
              AND p.oa_status IS NOT NULL
            GROUP BY p.oa_status
            ORDER BY count DESC
        """, oa_params)
        oa_facets = [{"value": r["value"], "count": r["count"]}
                     for r in cur.fetchall()]

        # --- Facette APC ---
        apc_conds = list(base_conditions)
        apc_params: list = []
        add_common(apc_conds, apc_params, skip="apc")
        apc_where = " AND ".join(apc_conds) if apc_conds else "TRUE"
        cur.execute(f"""
            SELECT
                COUNT(DISTINCT p.id) FILTER (WHERE EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169
                )) AS apc_uca,
                COUNT(DISTINCT p.id) FILTER (WHERE EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                ) AND NOT EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169
                )) AS apc_non_uca,
                COUNT(DISTINCT p.id) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                )) AS apc_none
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            WHERE {apc_where}
        """, apc_params)
        ar = cur.fetchone()
        apc_facets = [
            {"value": "uca", "text": "APC UCA", "count": ar["apc_uca"]},
            {"value": "non_uca", "text": "APC hors UCA", "count": ar["apc_non_uca"]},
            {"value": "none", "text": "Sans APC", "count": ar["apc_none"]},
        ]

        return {"years": year_facets, "labs": lab_facets, "oa_statuses": oa_facets, "apc": apc_facets}

