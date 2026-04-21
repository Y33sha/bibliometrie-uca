"""Query services async pour /api/authorships/* (router admin authorships, §2.12)."""

from typing import Any

from domain.sources import AUTHOR_SOURCES_SQL


def _uca_authors_cte(lab_id: int = 0, with_pub_count: bool = False) -> tuple[str, list[Any]]:
    """Construit la CTE uca_authors unifiée (toutes sources)."""
    lab_filter = ""
    params: list[Any] = []
    if lab_id:
        lab_filter = " AND sa.structure_ids && %s::int[]"
        params = [[lab_id]]

    pub_count_col = ""
    if with_pub_count:
        pub_count_col = """,
                   (SELECT COUNT(DISTINCT sa2.source_publication_id)
                    FROM source_authorships sa2
                    WHERE sa2.source_person_id = sauth.id AND sa2.in_perimeter = TRUE) AS uca_pub_count"""

    cte = f"""
        WITH uca_authors AS (
            SELECT sauth.id, sauth.source, sauth.full_name, sauth.last_name, sauth.first_name,
                   sauth.orcid, sauth.source_ids->>'idhal' AS idhal,
                   CASE WHEN sauth.source = 'openalex' THEN sauth.source_id ELSE NULL END AS openalex_id,
                   (SELECT sa3.person_id FROM source_authorships sa3
                    WHERE sa3.source_person_id = sauth.id AND sa3.person_id IS NOT NULL LIMIT 1) AS person_id{pub_count_col}
            FROM source_persons sauth
            WHERE sauth.source IN {AUTHOR_SOURCES_SQL}
              AND EXISTS (
                  SELECT 1 FROM source_authorships sa
                  WHERE sa.source_person_id = sauth.id AND sa.in_perimeter = TRUE{lab_filter}
              )
        )
    """
    return cte, params


async def authorships_stats(cur: Any, lab_id: int) -> dict[str, Any]:
    """Statistiques auteurs UCA (total, liés, avec ORCID/idHAL)."""
    lab_filter = ""
    params: list[Any] = []
    if lab_id:
        lab_filter = " AND sa.structure_ids && %s::int[]"
        params = [[lab_id]]

    await cur.execute(
        f"""
        WITH uca_authors AS (
            SELECT sauth.id, sauth.source,
                   (SELECT sa3.person_id FROM source_authorships sa3
                    WHERE sa3.source_person_id = sauth.id AND sa3.person_id IS NOT NULL LIMIT 1) AS person_id,
                   sauth.orcid, sauth.source_ids->>'idhal' AS idhal
            FROM source_persons sauth
            WHERE EXISTS (
                SELECT 1 FROM source_authorships sa
                WHERE sa.source_person_id = sauth.id AND sa.in_perimeter = TRUE{lab_filter}
            )
            AND sauth.source IN {AUTHOR_SOURCES_SQL}
        )
        SELECT
            COUNT(*) AS total_uca_authors,
            COUNT(*) FILTER (WHERE person_id IS NOT NULL) AS linked_to_person,
            COUNT(*) FILTER (WHERE orcid IS NOT NULL) AS with_orcid,
            COUNT(*) FILTER (WHERE idhal IS NOT NULL) AS with_idhal
        FROM uca_authors
        """,
        params,
    )
    return await cur.fetchone()


async def authorships_facets(
    cur: Any, *, linked: str, has_orcid: str, has_idhal: str, lab_id: int
) -> dict[str, Any]:
    """Facettes dynamiques pour la page authorships admin (chaque facette exclut son filtre)."""
    cte, cte_params = _uca_authors_cte(lab_id=lab_id)

    def build_where(*, skip: str) -> tuple[str, list[Any]]:
        conds: list[str] = []
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
        return where, []

    where, p = build_where(skip="linked")
    await cur.execute(
        f"""{cte}
        SELECT
            COUNT(*) FILTER (WHERE ua.person_id IS NOT NULL) AS yes,
            COUNT(*) FILTER (WHERE ua.person_id IS NULL) AS no
        FROM uca_authors ua {where}
        """,
        cte_params + p,
    )
    linked_counts = await cur.fetchone()

    where, p = build_where(skip="has_orcid")
    await cur.execute(
        f"""{cte}
        SELECT
            COUNT(*) FILTER (WHERE ua.orcid IS NOT NULL) AS yes,
            COUNT(*) FILTER (WHERE ua.orcid IS NULL) AS no
        FROM uca_authors ua {where}
        """,
        cte_params + p,
    )
    orcid_counts = await cur.fetchone()

    where, p = build_where(skip="has_idhal")
    await cur.execute(
        f"""{cte}
        SELECT
            COUNT(*) FILTER (WHERE ua.idhal IS NOT NULL) AS yes,
            COUNT(*) FILTER (WHERE ua.idhal IS NULL) AS no
        FROM uca_authors ua {where}
        """,
        cte_params + p,
    )
    idhal_counts = await cur.fetchone()

    where, p = build_where(skip="lab")
    lab_cte, lab_params = _uca_authors_cte(lab_id=0)
    lab_cte += f""",
        author_structs AS (
            SELECT sauth.id AS author_id, sauth.source, unnest(sa2.structure_ids) AS struct_id
            FROM source_persons sauth
            JOIN source_authorships sa2 ON sa2.source_person_id = sauth.id
            WHERE sa2.in_perimeter = TRUE AND sa2.structure_ids IS NOT NULL
              AND sauth.source IN {AUTHOR_SOURCES_SQL}
        )
    """
    await cur.execute(
        f"""{lab_cte}
        SELECT s.id AS value, COALESCE(s.acronym, s.name) AS label,
               COUNT(DISTINCT (ast.author_id, ast.source)) AS count
        FROM author_structs ast
        JOIN uca_authors ua ON ua.id = ast.author_id AND ua.source = ast.source
        JOIN structures s ON s.id = ast.struct_id
        {where} {"AND" if where else "WHERE"} s.structure_type = 'labo'
        GROUP BY s.id, s.acronym, s.name
        ORDER BY count DESC
        """,
        lab_params + p,
    )
    lab_facets = await cur.fetchall()

    return {
        "linked": {"yes": linked_counts["yes"], "no": linked_counts["no"]},
        "orcid": {"yes": orcid_counts["yes"], "no": orcid_counts["no"]},
        "idhal": {"yes": idhal_counts["yes"], "no": idhal_counts["no"]},
        "labs": lab_facets,
    }


async def list_authorships(
    cur: Any,
    *,
    search: str,
    linked: str,
    has_orcid: str,
    has_idhal: str,
    lab_id: int,
    page: int,
    per_page: int,
) -> dict[str, Any]:
    """Liste paginée des auteurs UCA avec filtres."""
    offset = (page - 1) * per_page
    cte, cte_params = _uca_authors_cte(lab_id=lab_id, with_pub_count=True)

    conditions: list[str] = []
    params: list[Any] = []
    if search:
        conditions.append(
            "(unaccent(ua.full_name) ILIKE unaccent(%s) OR ua.orcid ILIKE %s OR ua.idhal ILIKE %s)"
        )
        s = f"%{search}%"
        params.extend([s, s, s])
    if linked == "yes":
        conditions.append("ua.person_id IS NOT NULL")
    elif linked == "no":
        conditions.append("ua.person_id IS NULL")
    if has_orcid == "yes":
        conditions.append("ua.orcid IS NOT NULL")
    elif has_orcid == "no":
        conditions.append("ua.orcid IS NULL")
    if has_idhal == "yes":
        conditions.append("ua.idhal IS NOT NULL")
    elif has_idhal == "no":
        conditions.append("ua.idhal IS NULL")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    await cur.execute(
        f"""{cte}
        SELECT COUNT(*) FROM uca_authors ua {where}
        """,
        cte_params + params,
    )
    row = await cur.fetchone()
    total = row["count"]

    await cur.execute(
        f"""{cte}
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
        """,
        cte_params + params + [offset, per_page],
    )
    authors = await cur.fetchall()
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "authors": authors,
    }
