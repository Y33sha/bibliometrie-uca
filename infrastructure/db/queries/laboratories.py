"""Query services pour /api/laboratories/*."""

import datetime
from dataclasses import dataclass
from typing import Any

from infrastructure.db.queries.filters import (
    apply_person_has_identifier_filter,
    apply_person_has_rh_filter,
    persons_sort_clause,
)


def list_laboratories(cur: Any) -> list[dict[str, Any]]:
    """Liste des labos du périmètre, avec leurs tutelles (hors racines du périmètre)."""
    from infrastructure.app_config import _get_from_db
    from infrastructure.perimeter import get_persons_structure_ids

    perimeter_ids = list(get_persons_structure_ids(cur))
    perim_code = _get_from_db(cur, "perimeter_persons") or "uca"
    cur.execute("SELECT structure_ids FROM perimeters WHERE code = %s", (perim_code,))
    row = cur.fetchone()
    root_ids = (row["structure_ids"] if isinstance(row, dict) else row[0]) if row else []

    cur.execute(
        """
        SELECT s.id, s.code, s.name, s.acronym,
               s.ror_id, s.hal_collection,
               (SELECT json_agg(json_build_object(
                   'id', sp.id, 'name', sp.name, 'acronym', sp.acronym,
                   'type', sp.structure_type::text
               ) ORDER BY sp.name)
                FROM structure_relations sr
                JOIN structures sp ON sp.id = sr.parent_id
                WHERE sr.child_id = s.id
                  AND sr.relation_type = 'est_tutelle_de'
                  AND NOT (sp.id = ANY(%s))
               ) AS tutelles
        FROM structures s
        WHERE s.structure_type = 'labo'
          AND s.id = ANY(%s)
        ORDER BY s.name
        """,
        (root_ids, perimeter_ids),
    )
    return cur.fetchall()


def get_laboratory(cur: Any, lab_id: int) -> dict[str, Any] | None:
    """Profil public d'un laboratoire (None si absent)."""
    cur.execute(
        """
        SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text AS type,
               s.ror_id, s.rnsr_id, s.hal_collection
        FROM structures s
        WHERE s.id = %s
        """,
        (lab_id,),
    )
    struct = cur.fetchone()
    if not struct:
        return None

    cur.execute(
        """
        SELECT sp.id, sp.name, sp.acronym, sp.structure_type::text AS type,
               sr.relation_type
        FROM structure_relations sr
        JOIN structures sp ON sp.id = sr.parent_id
        WHERE sr.child_id = %s
        ORDER BY sr.relation_type, sp.name
        """,
        (lab_id,),
    )
    parents = cur.fetchall()

    cur.execute(
        """
        SELECT sc.id, sc.name, sc.acronym, sc.structure_type::text AS type,
               sr.relation_type
        FROM structure_relations sr
        JOIN structures sc ON sc.id = sr.child_id
        WHERE sr.parent_id = %s
        ORDER BY sc.name
        """,
        (lab_id,),
    )
    children = cur.fetchall()

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM publications p
        JOIN authorships a ON a.publication_id = p.id
        WHERE p.doc_type IN ('thesis', 'ongoing_thesis')
          AND %s = ANY(a.structure_ids)
          AND a.roles && ARRAY['author']::text[]
        """,
        (lab_id,),
    )
    theses_count = cur.fetchone()["count"]

    return {
        "structure": struct,
        "parents": parents,
        "children": children,
        "theses_count": theses_count,
    }


@dataclass(frozen=True, slots=True)
class LabPersonsFilters:
    search: str = ""
    has_rh: str = ""
    has_orcid: str = ""
    has_idhal: str = ""


def get_laboratory_persons(  # noqa: C901 (4 facettes × similar conditions)
    cur: Any, lab_id: int, *, filters: LabPersonsFilters, page: int, per_page: int, sort: str
) -> dict[str, Any]:
    """Personnes liées à un labo + authorships orphelines + facettes."""
    offset = (page - 1) * per_page
    lab_arr = [lab_id]

    extra_conds: list[str] = []
    extra_params: list[Any] = []
    if filters.search:
        extra_conds.append("""(
            unaccent(p.last_name) ILIKE unaccent(%s)
            OR unaccent(p.first_name) ILIKE unaccent(%s)
        )""")
        s = f"%{filters.search}%"
        extra_params.extend([s, s])
    apply_person_has_rh_filter(extra_conds, filters.has_rh)
    apply_person_has_identifier_filter(extra_conds, "orcid", filters.has_orcid)
    apply_person_has_identifier_filter(extra_conds, "idhal", filters.has_idhal)
    extra_where = (" AND " + " AND ".join(extra_conds)) if extra_conds else ""

    cur.execute(
        f"""
        SELECT COUNT(DISTINCT a.person_id)
        FROM authorships a
        JOIN persons p ON p.id = a.person_id
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE a.person_id IS NOT NULL
          AND a.structure_ids && %s::int[]
          AND a.roles && ARRAY['author']::text[]
          {extra_where}
        """,
        [lab_arr] + extra_params,
    )
    total_persons = cur.fetchone()["count"]

    order_clause = persons_sort_clause(sort)
    cur.execute(
        f"""
        SELECT p.id, p.last_name, p.first_name,
               prh.role_title, prh.department_name,
               (prh.id IS NOT NULL) AS has_rh,
               COUNT(DISTINCT a.publication_id) AS pub_count,
               (SELECT json_agg(json_build_object(
                    'value', pi.id_value, 'confirmed', (pi.status = 'confirmed')
                ) ORDER BY pi.id_value)
                FROM person_identifiers pi
                WHERE pi.person_id = p.id AND pi.id_type = 'orcid'
                  AND pi.status != 'rejected'
               ) AS orcids
        FROM authorships a
        JOIN persons p ON p.id = a.person_id
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE a.person_id IS NOT NULL
          AND a.structure_ids && %s::int[]
          AND a.roles && ARRAY['author']::text[]
          {extra_where}
        GROUP BY p.id, p.last_name, p.first_name,
                 prh.id, prh.role_title, prh.department_name
        ORDER BY {order_clause}
        LIMIT %s OFFSET %s
        """,
        [lab_arr] + extra_params + [per_page, offset],
    )
    persons = cur.fetchall()

    cur.execute(
        """
        SELECT COUNT(DISTINCT a.id)
        FROM authorships a
        WHERE a.person_id IS NULL
          AND a.structure_ids && %s::int[]
          AND a.roles && ARRAY['author']::text[]
        """,
        (lab_arr,),
    )
    orphan_total = cur.fetchone()["count"]

    # Facettes (chacune exclut son propre filtre)
    def facet_base(*, skip: str) -> tuple[str, list[Any]]:
        conds = [
            "a.person_id IS NOT NULL",
            "a.structure_ids && %s::int[]",
            "a.roles && ARRAY['author']::text[]",
        ]
        p: list[Any] = [lab_arr]
        if skip != "search" and filters.search:
            conds.append(
                "(unaccent(per.last_name) ILIKE unaccent(%s) "
                "OR unaccent(per.first_name) ILIKE unaccent(%s))"
            )
            s = f"%{filters.search}%"
            p.extend([s, s])
        if skip != "has_rh":
            if filters.has_rh == "yes":
                conds.append("prh.id IS NOT NULL")
            elif filters.has_rh == "no":
                conds.append("prh.id IS NULL")
        for key, val in (("has_orcid", filters.has_orcid), ("has_idhal", filters.has_idhal)):
            if skip != key:
                id_type = "orcid" if key == "has_orcid" else "idhal"
                if val == "yes":
                    conds.append(
                        f"EXISTS (SELECT 1 FROM person_identifiers pi "
                        f"WHERE pi.person_id = per.id AND pi.id_type = '{id_type}' "
                        f"AND pi.status != 'rejected')"
                    )
                elif val == "no":
                    conds.append(
                        f"NOT EXISTS (SELECT 1 FROM person_identifiers pi "
                        f"WHERE pi.person_id = per.id AND pi.id_type = '{id_type}' "
                        f"AND pi.status != 'rejected')"
                    )
        return " AND ".join(conds), p

    def run_facet(skip: str) -> dict[str, Any]:
        w, p = facet_base(skip=skip)
        cur.execute(
            f"""
            SELECT
                COUNT(DISTINCT per.id) FILTER (WHERE prh.id IS NOT NULL) AS rh_yes,
                COUNT(DISTINCT per.id) FILTER (WHERE prh.id IS NULL) AS rh_no,
                COUNT(DISTINCT per.id) FILTER (WHERE EXISTS (
                    SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
                )) AS orcid_yes,
                COUNT(DISTINCT per.id) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
                )) AS orcid_no,
                COUNT(DISTINCT per.id) FILTER (WHERE EXISTS (
                    SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id AND pi.id_type = 'idhal' AND pi.status != 'rejected'
                )) AS idhal_yes,
                COUNT(DISTINCT per.id) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM person_identifiers pi WHERE pi.person_id = per.id AND pi.id_type = 'idhal' AND pi.status != 'rejected'
                )) AS idhal_no
            FROM authorships a
            JOIN persons per ON per.id = a.person_id
            LEFT JOIN persons_rh prh ON prh.person_id = per.id
            WHERE {w}
            """,
            p,
        )
        return cur.fetchone()

    facet_rh = run_facet("has_rh")
    facet_orcid = run_facet("has_orcid")
    facet_idhal = run_facet("has_idhal")

    return {
        "total_persons": total_persons,
        "page": page,
        "per_page": per_page,
        "pages": (total_persons + per_page - 1) // per_page or 1,
        "persons": persons,
        "orphan_authorships": {"total": orphan_total},
        "facets": {
            "rh": {"yes": facet_rh["rh_yes"], "no": facet_rh["rh_no"]},
            "orcid": {"yes": facet_orcid["orcid_yes"], "no": facet_orcid["orcid_no"]},
            "idhal": {"yes": facet_idhal["idhal_yes"], "no": facet_idhal["idhal_no"]},
        },
    }


def get_laboratory_addresses(cur: Any, lab_id: int, *, page: int, per_page: int) -> dict[str, Any]:
    """Adresses liées à un laboratoire."""
    offset = (page - 1) * per_page
    cur.execute(
        """
        SELECT COUNT(*)
        FROM addresses a
        JOIN address_structures ast ON ast.address_id = a.id
        WHERE ast.structure_id = %s
          AND ast.is_confirmed IS DISTINCT FROM FALSE
        """,
        (lab_id,),
    )
    total = cur.fetchone()["count"]

    cur.execute(
        """
        SELECT a.id, a.raw_text, ast.is_confirmed
        FROM addresses a
        JOIN address_structures ast ON ast.address_id = a.id
        WHERE ast.structure_id = %s
          AND ast.is_confirmed IS DISTINCT FROM FALSE
        ORDER BY a.raw_text
        LIMIT %s OFFSET %s
        """,
        (lab_id, per_page, offset),
    )
    addresses = cur.fetchall()
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "addresses": addresses,
    }


def get_laboratory_dashboard(cur: Any, lab_id: int) -> dict[str, Any]:
    """Dashboard labo : publis/an, répartition OA, collab internationales, top pays."""
    lab_arr = [lab_id]
    current_year = datetime.date.today().year

    cur.execute(
        """
        SELECT p.pub_year, COUNT(DISTINCT p.id) AS count
        FROM publications p
        JOIN authorships a ON a.publication_id = p.id
        WHERE a.in_perimeter = TRUE
          AND a.structure_ids && %s::int[]
          AND a.roles && ARRAY['author']::text[]
          AND p.pub_year IS NOT NULL
          AND p.pub_year >= %s
        GROUP BY p.pub_year
        ORDER BY p.pub_year
        """,
        (lab_arr, current_year - 6),
    )
    pubs_by_year = [{"year": r["pub_year"], "count": r["count"]} for r in cur.fetchall()]

    cur.execute(
        """
        SELECT
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status NOT IN ('closed', 'unknown') AND p.oa_status IS NOT NULL) AS open_access,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown' OR p.oa_status IS NULL) AS unknown,
            COUNT(DISTINCT p.id) AS total
        FROM publications p
        JOIN authorships a ON a.publication_id = p.id
        WHERE a.in_perimeter = TRUE
          AND a.structure_ids && %s::int[]
          AND a.roles && ARRAY['author']::text[]
        """,
        (lab_arr,),
    )
    oa = cur.fetchone()

    cur.execute(
        """
        SELECT
            COUNT(DISTINCT p.id) AS total_articles,
            COUNT(DISTINCT p.id) FILTER (
                WHERE p.countries IS NOT NULL
                  AND EXISTS (SELECT 1 FROM unnest(p.countries) c WHERE c <> 'fr')
            ) AS international
        FROM publications p
        JOIN authorships a ON a.publication_id = p.id
        WHERE a.in_perimeter = TRUE
          AND a.structure_ids && %s::int[]
          AND a.roles && ARRAY['author']::text[]
          AND p.doc_type = 'article'
        """,
        (lab_arr,),
    )
    collab = cur.fetchone()

    cur.execute(
        """
        SELECT co.code, co.name, COUNT(DISTINCT p.id) AS count
        FROM publications p
        JOIN authorships a ON a.publication_id = p.id,
             unnest(p.countries) AS cc
        JOIN countries co ON co.code = cc
        WHERE a.in_perimeter = TRUE
          AND a.structure_ids && %s::int[]
          AND a.roles && ARRAY['author']::text[]
          AND p.doc_type = 'article'
          AND cc <> 'fr'
        GROUP BY co.code, co.name
        ORDER BY count DESC
        LIMIT 5
        """,
        (lab_arr,),
    )
    top_countries = [
        {"code": r["code"].strip(), "name": r["name"], "count": r["count"]} for r in cur.fetchall()
    ]

    return {
        "pubs_by_year": pubs_by_year,
        "oa": {
            "open_access": oa["open_access"],
            "closed": oa["closed"],
            "unknown": oa["unknown"],
            "total": oa["total"],
        },
        "collab": {
            "total_articles": collab["total_articles"],
            "international": collab["international"],
            "domestic": collab["total_articles"] - collab["international"],
        },
        "top_countries": top_countries,
    }
