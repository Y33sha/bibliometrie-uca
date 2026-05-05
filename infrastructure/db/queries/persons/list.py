"""Annuaire public + autocomplete + liste admin des personnes (async)."""

from dataclasses import dataclass, field
from typing import Any

from infrastructure.db.queries.filters import (
    apply_person_has_identifier_filter,
    apply_person_has_rh_filter,
    apply_person_linked_filter,
    persons_sort_clause,
)

# ── Annuaire public ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DirectoryFilters:
    search: str = ""
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: str = ""
    has_idhal: str = ""
    has_idref: str = ""
    has_rh: str = ""


async def persons_directory(
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
    apply_person_has_identifier_filter(conditions, "idref", filters.has_idref)
    apply_person_has_rh_filter(conditions, filters.has_rh)

    where = "WHERE " + " AND ".join(conditions)
    order = persons_sort_clause(sort)

    await cur.execute(
        f"SELECT COUNT(*) FROM persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id {where}",
        params,
    )
    row = await cur.fetchone()
    total = row["count"]

    await cur.execute(
        f"""
        SELECT
            p.id, p.last_name, p.first_name,
            prh.role_title, prh.department_name,
            (prh.id IS NOT NULL) AS has_rh,
            (SELECT COUNT(DISTINCT a.publication_id)
             FROM authorships a
             WHERE a.person_id = p.id AND a.roles && ARRAY['author']::text[]
            ) AS pub_count,
            (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status = 'confirmed')))
             FROM person_identifiers pi
             WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
            ) AS orcids,
            (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status = 'confirmed')))
             FROM person_identifiers pi
             WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected'
            ) AS idhals,
            (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status = 'confirmed')))
             FROM person_identifiers pi
             WHERE pi.person_id = p.id AND pi.id_type = 'idref' AND pi.status != 'rejected'
            ) AS idrefs
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
        "persons": await cur.fetchall(),
    }


# ── Autocomplete ─────────────────────────────────────────────────


async def search_persons(cur: Any, *, q: str, limit: int) -> list[dict[str, Any]]:
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
    await cur.execute(
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
    return await cur.fetchall()


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


async def list_persons(
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

    await cur.execute(
        f"SELECT COUNT(*) FROM persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id {where}",
        params,
    )
    row = await cur.fetchone()
    total = row["count"]

    await cur.execute(
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
    persons_rows = await cur.fetchall()
    person_ids = [p["id"] for p in persons_rows]

    identifiers_map: dict[int, Any] = {}
    if person_ids:
        await cur.execute(
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
        for r in await cur.fetchall():
            identifiers_map[r["person_id"]] = r["identifiers"]

    name_forms_map: dict[int, Any] = {}
    if person_ids:
        await cur.execute(
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
        for r in await cur.fetchall():
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
