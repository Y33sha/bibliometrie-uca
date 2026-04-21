"""Facettes dynamiques + listes de référence (départements, rôles, stats) (§2.12 : async)."""

from dataclasses import dataclass, field
from typing import Any

from infrastructure.db.queries.filters import (
    apply_person_has_identifier_filter,
    apply_person_has_rh_filter,
    apply_person_linked_filter,
)


@dataclass(frozen=True, slots=True)
class FacetFilters:
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: str = ""
    has_idhal: str = ""
    has_rh: str = ""
    linked: str = ""


async def persons_facets(cur: Any, *, filters: FacetFilters) -> dict[str, Any]:
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
    await cur.execute(
        f"""
        SELECT prh.department_name AS value, COUNT(*) AS count
        FROM {base_from}
        {where} {"AND" if c else "WHERE"} prh.department_name IS NOT NULL
        GROUP BY prh.department_name ORDER BY count DESC
        """,
        p,
    )
    dept_facets = await cur.fetchall()

    # RÔLES
    c, p = base_filters(skip="role")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    await cur.execute(
        f"""
        SELECT prh.role_title AS value, COUNT(*) AS count
        FROM {base_from}
        {where} {"AND" if c else "WHERE"} prh.role_title IS NOT NULL
        GROUP BY prh.role_title ORDER BY count DESC
        """,
        p,
    )
    role_facets = await cur.fetchall()

    # ORCID
    c, p = base_filters(skip="has_orcid")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    await cur.execute(
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
    orcid_counts = await cur.fetchone()

    # IDHAL
    c, p = base_filters(skip="has_idhal")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    await cur.execute(
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
    idhal_counts = await cur.fetchone()

    # RH
    c, p = base_filters(skip="has_rh")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    await cur.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE prh.id IS NOT NULL) AS yes,
            COUNT(*) FILTER (WHERE prh.id IS NULL) AS no
        FROM {base_from} {where}
        """,
        p,
    )
    rh_counts = await cur.fetchone()

    # LINKED
    c, p = base_filters(skip="linked")
    where = ("WHERE " + " AND ".join(c)) if c else ""
    await cur.execute(
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
    linked_counts = await cur.fetchone()

    return {
        "departments": dept_facets,
        "roles": role_facets,
        "orcid": {"yes": orcid_counts["yes"], "no": orcid_counts["no"]},
        "idhal": {"yes": idhal_counts["yes"], "no": idhal_counts["no"]},
        "rh": {"yes": rh_counts["yes"], "no": rh_counts["no"]},
        "linked": {"yes": linked_counts["yes"], "no": linked_counts["no"]},
    }


# ── Listes de référence ──────────────────────────────────────────


async def list_departments(cur: Any) -> list[dict[str, Any]]:
    """Liste des départements distincts."""
    await cur.execute("""
        SELECT department_name, COUNT(*) AS count
        FROM persons_rh
        WHERE department_name IS NOT NULL
        GROUP BY department_name
        ORDER BY count DESC
    """)
    return await cur.fetchall()


async def list_roles(cur: Any) -> list[dict[str, Any]]:
    """Liste des rôles distincts."""
    await cur.execute("""
        SELECT role_title, COUNT(*) AS count
        FROM persons_rh
        WHERE role_title IS NOT NULL
        GROUP BY role_title
        ORDER BY count DESC
    """)
    return await cur.fetchall()


async def persons_stats(cur: Any) -> dict[str, Any]:
    """Statistiques globales personnes."""
    await cur.execute("""
        SELECT
            (SELECT COUNT(*) FROM persons) AS total_persons,
            (SELECT COUNT(DISTINCT person_id) FROM authorships WHERE person_id IS NOT NULL) AS linked_persons,
            (SELECT COUNT(*) FROM authorships WHERE person_id IS NOT NULL) AS linked_authors,
            (SELECT COUNT(DISTINCT department_name)
             FROM persons_rh WHERE department_name IS NOT NULL) AS departments
    """)
    return await cur.fetchone()
