"""Query services pour /api/persons/* — endpoints de lecture principaux.

Couvre : directory, search, list, facets, departments, roles, stats,
detail (get_person), profile, theses, addresses.

Les endpoints admin (HAL-problems, orphan-authorships, name-form-authorships)
restent dans le router pour l'instant — seront traités dans le reliquat.
"""

from dataclasses import dataclass, field
from typing import Any

from infrastructure.db.queries.filters import (
    apply_person_has_identifier_filter,
    apply_person_has_rh_filter,
    apply_person_linked_filter,
)

# ── Annuaire public ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DirectoryFilters:
    search: str = ""
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: str = ""
    has_idhal: str = ""
    has_rh: str = ""


_DIR_SORT_MAP = {
    "name": "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC",
    "-name": "LOWER(p.last_name) DESC, LOWER(p.first_name) DESC",
}


def persons_directory(
    cur: Any, *, filters: DirectoryFilters, page: int, per_page: int, sort: str
) -> dict[str, Any]:
    """Annuaire public des personnes avec ORCID et idHAL."""
    offset = (page - 1) * per_page
    conditions = ["p.rejected = FALSE"]
    params: list[Any] = []

    if filters.search:
        conditions.append(
            "(unaccent(p.last_name) ILIKE unaccent(%s) OR unaccent(p.first_name) ILIKE unaccent(%s))"
        )
        s = f"%{filters.search}%"
        params.extend([s, s])
    if filters.departments:
        conditions.append("prh.department_name = ANY(%s)")
        params.append(filters.departments)
    if filters.roles:
        conditions.append("prh.role_title = ANY(%s)")
        params.append(filters.roles)
    apply_person_has_identifier_filter(conditions, "orcid", filters.has_orcid)
    apply_person_has_identifier_filter(conditions, "idhal", filters.has_idhal)
    apply_person_has_rh_filter(conditions, filters.has_rh)

    where = "WHERE " + " AND ".join(conditions)
    order = _DIR_SORT_MAP.get(sort, _DIR_SORT_MAP["name"])

    cur.execute(
        f"SELECT COUNT(*) FROM persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id {where}",
        params,
    )
    total = cur.fetchone()["count"]

    cur.execute(
        f"""
        SELECT
            p.id, p.last_name, p.first_name,
            prh.role_title, prh.department_name,
            (prh.id IS NOT NULL) AS has_rh,
            (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status = 'confirmed')))
             FROM person_identifiers pi
             WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
            ) AS orcids,
            (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status = 'confirmed')))
             FROM person_identifiers pi
             WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected'
            ) AS idhals
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        {where}
        ORDER BY {order}
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "persons": cur.fetchall(),
    }


# ── Autocomplete ─────────────────────────────────────────────────


def search_persons(cur: Any, *, q: str, limit: int) -> list[dict[str, Any]]:
    """Recherche rapide (autocomplete) : chaque mot doit matcher dans last ou first name."""
    words = q.strip().split()
    if not words:
        return []
    conditions = ["p.rejected = FALSE"]
    params: list[Any] = []
    for w in words:
        s = f"%{w}%"
        conditions.append(
            "(unaccent(p.last_name) ILIKE unaccent(%s) OR unaccent(p.first_name) ILIKE unaccent(%s))"
        )
        params.extend([s, s])
    params.append(limit)
    cur.execute(
        f"""
        SELECT p.id, p.last_name, p.first_name, prh.department_name,
               (prh.id IS NOT NULL) AS has_rh
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE {" AND ".join(conditions)}
        ORDER BY LOWER(p.last_name), LOWER(p.first_name)
        LIMIT %s
        """,
        params,
    )
    return cur.fetchall()


# ── Liste admin ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ListFilters:
    search: str = ""
    department: str = ""
    role: str = ""
    linked: str = ""
    has_orcid: str = ""
    has_idhal: str = ""
    has_rh: str = ""


_LIST_SORT_MAP = {
    "name": "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC",
    "-name": "LOWER(p.last_name) DESC, LOWER(p.first_name) DESC",
    "pubs": "pub_count ASC, LOWER(p.last_name) ASC",
    "-pubs": "pub_count DESC, LOWER(p.last_name) ASC",
    "uca_pubs": "uca_pub_count ASC, LOWER(p.last_name) ASC",
    "-uca_pubs": "uca_pub_count DESC, LOWER(p.last_name) ASC",
}


def list_persons(
    cur: Any, *, filters: ListFilters, page: int, per_page: int, sort: str
) -> dict[str, Any]:
    """Liste des personnes avec filtres (admin)."""
    offset = (page - 1) * per_page
    conditions: list[str] = []
    params: list[Any] = []

    if filters.search:
        conditions.append("""(
            unaccent(p.last_name) ILIKE unaccent(%s) OR unaccent(p.first_name) ILIKE unaccent(%s)
            OR prh.email ILIKE %s OR unaccent(prh.department_name) ILIKE unaccent(%s)
        )""")
        s = f"%{filters.search}%"
        params.extend([s, s, s, s])
    if filters.department:
        conditions.append("prh.department_name = %s")
        params.append(filters.department)
    if filters.role:
        conditions.append("prh.role_title = %s")
        params.append(filters.role)
    apply_person_linked_filter(conditions, filters.linked)
    apply_person_has_identifier_filter(conditions, "orcid", filters.has_orcid)
    apply_person_has_identifier_filter(conditions, "idhal", filters.has_idhal)
    apply_person_has_rh_filter(conditions, filters.has_rh)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = _LIST_SORT_MAP.get(sort, _LIST_SORT_MAP["name"])

    cur.execute(
        f"SELECT COUNT(*) FROM persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id {where}",
        params,
    )
    total = cur.fetchone()["count"]

    cur.execute(
        f"""
        SELECT p.id, p.last_name, p.first_name,
            p.last_name_normalized, p.first_name_normalized,
            prh.role_title, prh.department_name, prh.start_date, prh.end_date,
            (prh.id IS NOT NULL) AS has_rh, p.rejected,
            (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id) AS pub_count,
            (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id AND a.in_perimeter = TRUE) AS uca_pub_count
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        {where}
        ORDER BY {order}
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    persons_rows = cur.fetchall()
    person_ids = [p["id"] for p in persons_rows]

    identifiers_map: dict[int, Any] = {}
    if person_ids:
        cur.execute(
            """
            SELECT pi.person_id,
                   json_agg(json_build_object(
                       'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                       'source', pi.source, 'status', pi.status
                   ) ORDER BY pi.id_type, pi.id_value) AS identifiers
            FROM person_identifiers pi
            WHERE pi.person_id = ANY(%s)
            GROUP BY pi.person_id
            """,
            (person_ids,),
        )
        for r in cur.fetchall():
            identifiers_map[r["person_id"]] = r["identifiers"]

    name_forms_map: dict[int, Any] = {}
    if person_ids:
        cur.execute(
            """
            SELECT pid AS person_id,
                   json_agg(json_build_object(
                       'name_form', pnf.name_form,
                       'sources', pnf.sources,
                       'ambiguous', (array_length(pnf.person_ids, 1) > 1)
                   ) ORDER BY pnf.name_form) AS name_forms
            FROM person_name_forms pnf,
                 LATERAL unnest(pnf.person_ids) AS pid
            WHERE pid = ANY(%s)
              AND pnf.sources IS NOT NULL
              AND NOT (pnf.sources = ARRAY['persons']::text[])
            GROUP BY pid
            """,
            (person_ids,),
        )
        for r in cur.fetchall():
            name_forms_map[r["person_id"]] = r["name_forms"]

    for p in persons_rows:
        p["identifiers"] = identifiers_map.get(p["id"])
        p["name_forms"] = name_forms_map.get(p["id"])

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "persons": persons_rows,
    }


# ── Facettes ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FacetFilters:
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: str = ""
    has_idhal: str = ""
    has_rh: str = ""
    linked: str = ""


def persons_facets(cur: Any, *, filters: FacetFilters) -> dict[str, Any]:
    """Facettes dynamiques (chaque facette exclut son propre filtre)."""

    def base_filters(*, skip: str) -> tuple[list[str], list[Any]]:
        conds: list[str] = []
        params: list[Any] = []
        if skip != "department" and filters.departments:
            conds.append("prh.department_name = ANY(%s)")
            params.append(filters.departments)
        if skip != "role" and filters.roles:
            conds.append("prh.role_title = ANY(%s)")
            params.append(filters.roles)
        if skip != "has_orcid":
            apply_person_has_identifier_filter(conds, "orcid", filters.has_orcid)
        if skip != "has_idhal":
            apply_person_has_identifier_filter(conds, "idhal", filters.has_idhal)
        if skip != "has_rh":
            apply_person_has_rh_filter(conds, filters.has_rh)
        if skip != "linked":
            apply_person_linked_filter(conds, filters.linked)
        return conds, params

    base_from = "persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id"

    # DÉPARTEMENTS
    c, p = base_filters(skip="department")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    cur.execute(
        f"""
        SELECT prh.department_name AS value, COUNT(*) AS count
        FROM {base_from}
        {where} {"AND" if c else "WHERE"} prh.department_name IS NOT NULL
        GROUP BY prh.department_name ORDER BY count DESC
        """,
        p,
    )
    dept_facets = cur.fetchall()

    # RÔLES
    c, p = base_filters(skip="role")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    cur.execute(
        f"""
        SELECT prh.role_title AS value, COUNT(*) AS count
        FROM {base_from}
        {where} {"AND" if c else "WHERE"} prh.role_title IS NOT NULL
        GROUP BY prh.role_title ORDER BY count DESC
        """,
        p,
    )
    role_facets = cur.fetchall()

    # ORCID
    c, p = base_filters(skip="has_orcid")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    cur.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE EXISTS (
                SELECT 1 FROM person_identifiers pi
                WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
            )) AS yes,
            COUNT(*) FILTER (WHERE NOT EXISTS (
                SELECT 1 FROM person_identifiers pi
                WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
            )) AS no
        FROM {base_from} {where}
        """,
        p,
    )
    orcid_counts = cur.fetchone()

    # IDHAL
    c, p = base_filters(skip="has_idhal")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    cur.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE
                EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
            ) AS yes,
            COUNT(*) FILTER (WHERE
                NOT EXISTS (SELECT 1 FROM person_identifiers pi WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected')
            ) AS no
        FROM {base_from} {where}
        """,
        p,
    )
    idhal_counts = cur.fetchone()

    # RH
    c, p = base_filters(skip="has_rh")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    cur.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE prh.id IS NOT NULL) AS yes,
            COUNT(*) FILTER (WHERE prh.id IS NULL) AS no
        FROM {base_from} {where}
        """,
        p,
    )
    rh_counts = cur.fetchone()

    # LINKED
    c, p = base_filters(skip="linked")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    cur.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE
                EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)
            ) AS yes,
            COUNT(*) FILTER (WHERE
                NOT EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)
            ) AS no
        FROM {base_from} {where}
        """,
        p,
    )
    linked_counts = cur.fetchone()

    return {
        "departments": dept_facets,
        "roles": role_facets,
        "orcid": {"yes": orcid_counts["yes"], "no": orcid_counts["no"]},
        "idhal": {"yes": idhal_counts["yes"], "no": idhal_counts["no"]},
        "rh": {"yes": rh_counts["yes"], "no": rh_counts["no"]},
        "linked": {"yes": linked_counts["yes"], "no": linked_counts["no"]},
    }


# ── Listes de référence ──────────────────────────────────────────


def list_departments(cur: Any) -> list[dict[str, Any]]:
    """Liste des départements distincts."""
    cur.execute("""
        SELECT department_name, COUNT(*) AS count
        FROM persons_rh
        WHERE department_name IS NOT NULL
        GROUP BY department_name
        ORDER BY count DESC
    """)
    return cur.fetchall()


def list_roles(cur: Any) -> list[dict[str, Any]]:
    """Liste des rôles distincts."""
    cur.execute("""
        SELECT role_title, COUNT(*) AS count
        FROM persons_rh
        WHERE role_title IS NOT NULL
        GROUP BY role_title
        ORDER BY count DESC
    """)
    return cur.fetchall()


def persons_stats(cur: Any) -> dict[str, Any]:
    """Statistiques globales personnes."""
    cur.execute("""
        SELECT
            (SELECT COUNT(*) FROM persons) AS total_persons,
            (SELECT COUNT(DISTINCT person_id) FROM authorships WHERE person_id IS NOT NULL) AS linked_persons,
            (SELECT COUNT(*) FROM authorships WHERE person_id IS NOT NULL) AS linked_authors,
            (SELECT COUNT(DISTINCT department_name)
             FROM persons_rh WHERE department_name IS NOT NULL) AS departments
    """)
    return cur.fetchone()


# ── Détail ───────────────────────────────────────────────────────


def get_person(cur: Any, person_id: int) -> dict[str, Any] | None:
    """Détail d'une personne avec auteurs liés (admin)."""
    cur.execute(
        """
        SELECT p.id, p.last_name, p.first_name,
            p.last_name_normalized, p.first_name_normalized,
            prh.role_title, prh.department_name, prh.start_date, prh.end_date,
            (prh.id IS NOT NULL) AS has_rh,
            (SELECT json_agg(x) FROM (
                SELECT DISTINCT ON (sa.source, sa.source_person_id)
                       sa.source_person_id AS id, sa.source,
                       sa.raw_author_name AS full_name
                FROM source_authorships sa
                WHERE sa.person_id = p.id AND NOT sa.excluded
                ORDER BY sa.source, sa.source_person_id
            ) x) AS linked_authors,
            (SELECT json_agg(json_build_object(
                'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                'source', pi.source, 'status', pi.status
            ) ORDER BY pi.id_type, pi.id_value) FROM person_identifiers pi WHERE pi.person_id = p.id
            ) AS identifiers
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id = %s
        """,
        (person_id,),
    )
    return cur.fetchone()


def person_profile(cur: Any, person_id: int) -> dict[str, Any] | None:
    """Profil public : infos + identifiants + auteurs liés."""
    cur.execute(
        """
        SELECT p.id, p.last_name, p.first_name,
               prh.role_title, prh.department_name,
               prh.start_date, prh.end_date
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id = %s
        """,
        (person_id,),
    )
    person = cur.fetchone()
    if not person:
        return None

    cur.execute(
        """
        SELECT id, id_type, id_value, source, status
        FROM person_identifiers WHERE person_id = %s
        """,
        (person_id,),
    )
    identifiers = cur.fetchall()

    cur.execute(
        """
        SELECT DISTINCT sauth.id, 'hal' AS source, sauth.full_name, sauth.orcid,
               sauth.source_ids->>'idhal' AS idhal,
               (sauth.source_ids->>'hal_person_id')::int AS hal_person_id,
               NULL::text AS openalex_id,
               (SELECT COUNT(*) FROM source_authorships sa2
                WHERE sa2.source = 'hal' AND sa2.source_person_id = sauth.id
                  AND sa2.in_perimeter = TRUE AND NOT sa2.excluded) AS uca_pub_count
        FROM source_persons sauth
        JOIN source_authorships sa ON sa.source = 'hal' AND sa.source_person_id = sauth.id
        WHERE sa.person_id = %s AND NOT sa.excluded
        """,
        (person_id,),
    )
    hal_authors = cur.fetchall()

    cur.execute(
        """
        SELECT MIN(sa.id) AS id,
               sa.raw_author_name AS full_name,
               'openalex' AS source,
               NULL::text AS orcid, NULL::text AS idhal, NULL::text AS openalex_id,
               COUNT(*) FILTER (WHERE sa.in_perimeter = TRUE) AS uca_pub_count
        FROM source_authorships sa
        WHERE sa.source = 'openalex' AND sa.person_id = %s
        GROUP BY sa.raw_author_name
        """,
        (person_id,),
    )
    oa_authors = cur.fetchall()

    cur.execute(
        """
        SELECT sauth.id, 'wos' AS source, sa.raw_author_name AS full_name, sauth.orcid,
               NULL::text AS idhal, NULL::text AS openalex_id,
               (SELECT COUNT(*) FROM source_authorships sa2
                WHERE sa2.source = 'wos' AND sa2.source_person_id = sauth.id
                  AND sa2.in_perimeter = TRUE) AS uca_pub_count
        FROM source_persons sauth
        JOIN source_authorships sa ON sa.source = 'wos' AND sa.source_person_id = sauth.id
        WHERE sa.person_id = %s
        GROUP BY sauth.id, sa.raw_author_name, sauth.orcid
        """,
        (person_id,),
    )
    wos_authors = cur.fetchall()

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.person_id = %s
          AND sa.source = 'theses'
          AND NOT (sa.roles && ARRAY['author']::text[])
          AND sd.publication_id IS NOT NULL
        """,
        (person_id,),
    )
    theses_count = cur.fetchone()["count"]

    return {
        "person": person,
        "identifiers": identifiers,
        "authors": hal_authors + oa_authors + wos_authors,
        "theses_count": theses_count,
    }


# ── Thèses encadrées ─────────────────────────────────────────────


_THESIS_ROLES = ("thesis_director", "rapporteur", "jury_president", "jury_member")
_THESIS_ROLE_LABELS = {
    "thesis_director": "Directeur/directrice de thèse",
    "rapporteur": "Rapporteur",
    "jury_president": "Président du jury",
    "jury_member": "Membre du jury",
}


def person_theses(cur: Any, person_id: int) -> dict[str, Any]:
    """Thèses liées à cette personne avec un rôle non-auteur."""
    cur.execute(
        """
        SELECT p.id, p.title, p.pub_year, p.doi,
               sa.roles,
               (SELECT sa2.raw_author_name
                FROM source_authorships sa2
                WHERE sa2.source_publication_id = sd.id
                  AND sa2.source = 'theses'
                  AND sa2.roles && ARRAY['author']::text[]
                LIMIT 1
               ) AS author_name,
               (SELECT sa2.person_id
                FROM source_authorships sa2
                WHERE sa2.source_publication_id = sd.id
                  AND sa2.source = 'theses'
                  AND sa2.roles && ARRAY['author']::text[]
                LIMIT 1
               ) AS author_person_id,
               (SELECT ARRAY_AGG(DISTINCT sid)
                FROM authorships a,
                     UNNEST(a.structure_ids) AS sid
                JOIN structures st ON st.id = sid
                WHERE a.publication_id = p.id AND a.in_perimeter
                  AND st.structure_type = 'labo'
               ) AS structure_ids
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        JOIN publications p ON p.id = sd.publication_id
        WHERE sa.person_id = %s
          AND sa.source = 'theses'
          AND NOT (sa.roles && ARRAY['author']::text[])
        ORDER BY p.pub_year DESC NULLS LAST, p.title
        """,
        (person_id,),
    )
    rows = cur.fetchall()

    all_struct_ids: set[int] = set()
    for row in rows:
        for sid in row["structure_ids"] or []:
            all_struct_ids.add(sid)

    structures: dict[int, Any] = {}
    if all_struct_ids:
        cur.execute(
            "SELECT id, acronym, name FROM structures WHERE id = ANY(%s)",
            (list(all_struct_ids),),
        )
        for s in cur.fetchall():
            structures[s["id"]] = {"acronym": s["acronym"], "name": s["name"]}

    by_role: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        roles = row["roles"] or []
        role = "jury_member"
        for r in _THESIS_ROLES:
            if r in roles:
                role = r
                break
        by_role.setdefault(role, []).append(
            {
                "id": row["id"],
                "title": row["title"],
                "pub_year": row["pub_year"],
                "doi": row["doi"],
                "author_name": row["author_name"],
                "author_person_id": row["author_person_id"],
                "structure_ids": row["structure_ids"] or [],
            }
        )

    sections = [
        {"role": k, "label": _THESIS_ROLE_LABELS[k], "theses": by_role[k]}
        for k in _THESIS_ROLES
        if k in by_role
    ]
    return {"sections": sections, "total": len(rows), "structures": structures}


# ── Adresses ─────────────────────────────────────────────────────


def person_addresses(cur: Any, person_id: int, *, page: int, per_page: int) -> dict[str, Any]:
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    base_where = """a.id IN (
            SELECT DISTINCT saa.address_id
            FROM source_authorship_addresses saa
            JOIN source_authorships sa ON sa.id = saa.source_authorship_id
            WHERE sa.person_id = %s
        )"""
    cur.execute(f"SELECT COUNT(*) AS total FROM addresses a WHERE {base_where}", (person_id,))
    total = cur.fetchone()["total"]
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page

    cur.execute(
        f"""
        SELECT a.id, a.raw_text,
               (SELECT jsonb_agg(jsonb_build_object(
                    'id', s.id, 'acronym', s.acronym, 'name', s.name))
                FROM address_structures ast
                JOIN structures s ON s.id = ast.structure_id
                WHERE ast.address_id = a.id AND s.structure_type != 'site'
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
               ) AS structures
        FROM addresses a
        WHERE {base_where}
        ORDER BY a.raw_text
        LIMIT %s OFFSET %s
        """,
        (person_id, per_page, offset),
    )
    return {
        "total": total,
        "page": page,
        "pages": pages,
        "addresses": cur.fetchall(),
    }
