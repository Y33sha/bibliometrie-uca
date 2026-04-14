"""Auto-extracted router."""

from fastapi import APIRouter, Query, HTTPException
from backend.deps import get_cursor
from backend.filters import PUB_IS_UCA
from utils.sources import AUTHOR_SOURCES_SQL

router = APIRouter()

@router.get("/api/authorships/stats")
async def authorships_stats(lab_id: int = Query(0)):
    """Statistiques auteurs UCA."""
    lab_filter = ""
    params: list = []
    if lab_id:
        lab_filter = " AND sa.structure_ids && %s::int[]"
        params = [[lab_id]]

    with get_cursor() as (cur, conn):
        cur.execute(f"""
            WITH uca_authors AS (
                SELECT sauth.id, sa.source,
                       (SELECT sa3.person_id FROM source_authorships sa3
                        WHERE sa3.source_author_id = sauth.id AND sa3.person_id IS NOT NULL LIMIT 1) AS person_id,
                       sauth.orcid, sauth.source_ids->>'idhal' AS idhal
                FROM source_authors sauth
                WHERE EXISTS (
                    SELECT 1 FROM source_authorships sa
                    WHERE sa.source_author_id = sauth.id AND sa.in_perimeter = TRUE{lab_filter}
                )
                AND sauth.source IN {AUTHOR_SOURCES_SQL}
            )
            SELECT
                COUNT(*) AS total_uca_authors,
                COUNT(*) FILTER (WHERE person_id IS NOT NULL) AS linked_to_person,
                COUNT(*) FILTER (WHERE orcid IS NOT NULL) AS with_orcid,
                COUNT(*) FILTER (WHERE idhal IS NOT NULL) AS with_idhal
            FROM uca_authors
        """, params)
        return cur.fetchone()


def _uca_authors_cte(lab_id: int = 0, with_pub_count: bool = False) -> tuple[str, list]:
    """Construit la CTE uca_authors unifiee (toutes sources)."""
    lab_filter = ""
    params: list = []
    if lab_id:
        lab_filter = " AND sa.structure_ids && %s::int[]"
        params = [[lab_id]]

    pub_count_col = ""
    if with_pub_count:
        pub_count_col = """,
                   (SELECT COUNT(DISTINCT sa2.source_document_id)
                    FROM source_authorships sa2
                    WHERE sa2.source_author_id = sauth.id AND sa2.in_perimeter = TRUE) AS uca_pub_count"""

    cte = f"""
        WITH uca_authors AS (
            SELECT sauth.id, sauth.source, sauth.full_name, sauth.last_name, sauth.first_name,
                   sauth.orcid, sauth.source_ids->>'idhal' AS idhal,
                   CASE WHEN sauth.source = 'openalex' THEN sauth.source_id ELSE NULL END AS openalex_id,
                   (SELECT sa3.person_id FROM source_authorships sa3
                    WHERE sa3.source_author_id = sauth.id AND sa3.person_id IS NOT NULL LIMIT 1) AS person_id{pub_count_col}
            FROM source_authors sauth
            WHERE sauth.source IN {AUTHOR_SOURCES_SQL}
              AND EXISTS (
                  SELECT 1 FROM source_authorships sa
                  WHERE sa.source_author_id = sauth.id AND sa.in_perimeter = TRUE{lab_filter}
              )
        )
    """
    return cte, params


@router.get("/api/authorships/facets")
async def authorships_facets(
    linked: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    lab_id: int = Query(0),
):
    """Facettes dynamiques pour la page authorships admin."""
    cte, cte_params = _uca_authors_cte(lab_id=lab_id)

    def build_where(*, skip: str) -> tuple[str, list]:
        conds: list[str] = []
        params: list = []
        if skip != "linked":
            if linked == "yes":
                conds.append("ua.person_id IS NOT NULL")
            elif linked == "no":
                conds.append("ua.person_id IS NULL")
        if skip != "has_orcid":
            if has_orcid == "yes":
                conds.append("ua.orcid IS NOT NULL")
            elif has_orcid == "no":
                conds.append("ua.orcid IS NULL")
        if skip != "has_idhal":
            if has_idhal == "yes":
                conds.append("ua.idhal IS NOT NULL")
            elif has_idhal == "no":
                conds.append("ua.idhal IS NULL")
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        return where, params

    with get_cursor() as (cur, conn):
        # Linked
        where, p = build_where(skip="linked")
        cur.execute(f"""{cte}
            SELECT
                COUNT(*) FILTER (WHERE ua.person_id IS NOT NULL) AS yes,
                COUNT(*) FILTER (WHERE ua.person_id IS NULL) AS no
            FROM uca_authors ua {where}
        """, cte_params + p)
        linked_counts = cur.fetchone()

        # ORCID
        where, p = build_where(skip="has_orcid")
        cur.execute(f"""{cte}
            SELECT
                COUNT(*) FILTER (WHERE ua.orcid IS NOT NULL) AS yes,
                COUNT(*) FILTER (WHERE ua.orcid IS NULL) AS no
            FROM uca_authors ua {where}
        """, cte_params + p)
        orcid_counts = cur.fetchone()

        # idHAL
        where, p = build_where(skip="has_idhal")
        cur.execute(f"""{cte}
            SELECT
                COUNT(*) FILTER (WHERE ua.idhal IS NOT NULL) AS yes,
                COUNT(*) FILTER (WHERE ua.idhal IS NULL) AS no
            FROM uca_authors ua {where}
        """, cte_params + p)
        idhal_counts = cur.fetchone()

        # Labs (cross-filtered, excluding lab filter itself)
        where, p = build_where(skip="lab")
        lab_cte, lab_params = _uca_authors_cte(lab_id=0)
        lab_cte += """,
            author_structs AS (
                SELECT sauth.id AS author_id, sauth.source, unnest(sa2.structure_ids) AS struct_id
                FROM source_authors sauth
                JOIN source_authorships sa2 ON sa2.source_author_id = sauth.id
                WHERE sa2.in_perimeter = TRUE AND sa2.structure_ids IS NOT NULL
                  AND sauth.source IN {AUTHOR_SOURCES_SQL}
            )
        """
        cur.execute(f"""{lab_cte}
            SELECT s.id AS value, COALESCE(s.acronym, s.name) AS label,
                   COUNT(DISTINCT (ast.author_id, ast.source)) AS count
            FROM author_structs ast
            JOIN uca_authors ua ON ua.id = ast.author_id AND ua.source = ast.source
            JOIN structures s ON s.id = ast.struct_id
            {where} {"AND" if where else "WHERE"} s.structure_type = 'labo'
            GROUP BY s.id, s.acronym, s.name
            ORDER BY count DESC
        """, lab_params + p)
        lab_facets = cur.fetchall()

        return {
            "linked": {"yes": linked_counts["yes"], "no": linked_counts["no"]},
            "orcid": {"yes": orcid_counts["yes"], "no": orcid_counts["no"]},
            "idhal": {"yes": idhal_counts["yes"], "no": idhal_counts["no"]},
            "labs": lab_facets,
        }


@router.get("/api/authorships")
async def list_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    linked: str = Query(""),  # "yes", "no", ""
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    lab_id: int = Query(0),
):
    """Liste des auteurs UCA avec filtres."""
    offset = (page - 1) * per_page

    cte, cte_params = _uca_authors_cte(lab_id=lab_id, with_pub_count=True)

    # Filtres appliques sur le resultat du CTE
    cte_conditions = []
    params: list = []

    if search:
        cte_conditions.append("(unaccent(ua.full_name) ILIKE unaccent(%s) OR ua.orcid ILIKE %s OR ua.idhal ILIKE %s)")
        s = f"%{search}%"
        params.extend([s, s, s])
    if linked == "yes":
        cte_conditions.append("ua.person_id IS NOT NULL")
    elif linked == "no":
        cte_conditions.append("ua.person_id IS NULL")
    if has_orcid == "yes":
        cte_conditions.append("ua.orcid IS NOT NULL")
    elif has_orcid == "no":
        cte_conditions.append("ua.orcid IS NULL")
    if has_idhal == "yes":
        cte_conditions.append("ua.idhal IS NOT NULL")
    elif has_idhal == "no":
        cte_conditions.append("ua.idhal IS NULL")

    where = ("WHERE " + " AND ".join(cte_conditions)) if cte_conditions else ""

    with get_cursor() as (cur, conn):
        cur.execute(f"""
            {cte}
            SELECT COUNT(*) FROM uca_authors ua {where}
        """, cte_params + params)
        total = cur.fetchone()["count"]

        cur.execute(f"""
            {cte}
            SELECT ua.id, ua.source, ua.full_name, ua.last_name, ua.first_name,
                   ua.orcid, ua.idhal, ua.openalex_id, ua.person_id,
                   ua.uca_pub_count,
                   (SELECT json_build_object(
                       'id', p.id, 'last_name', p.last_name,
                       'first_name', p.first_name, 'department_name', prh.department_name,
                       'role_title', prh.role_title,
                       'has_rh', (prh.id IS NOT NULL)
                   ) FROM persons p
                   LEFT JOIN persons_rh prh ON prh.person_id = p.id
                   WHERE p.id = ua.person_id) AS person
            FROM uca_authors ua
            {where}
            ORDER BY ua.uca_pub_count DESC, ua.full_name
            OFFSET %s LIMIT %s
        """, cte_params + params + [offset, per_page])

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "authors": cur.fetchall(),
        }


# =============================================================
# PERSONNES (données RH)
# =============================================================
