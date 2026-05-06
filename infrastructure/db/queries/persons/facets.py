"""Facettes dynamiques + listes de référence (départements, rôles, stats) — async."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from infrastructure.db.queries.filters import (
    WhereClause,
    assemble_where,
    person_has_identifier_clause,
    person_has_rh_clause,
    person_linked_clause,
)


@dataclass(frozen=True, slots=True)
class FacetFilters:
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: str = ""
    has_idhal: str = ""
    has_idref: str = ""
    has_rh: str = ""
    linked: str = ""


_BASE_FROM = "persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id"


async def persons_facets(conn: AsyncConnection, *, filters: FacetFilters) -> dict[str, Any]:
    """Facettes dynamiques (chaque facette exclut son propre filtre)."""

    def base_clauses(*, skip: str) -> list[WhereClause | None]:
        out: list[WhereClause | None] = []
        if skip != "department" and filters.departments:
            out.append(
                WhereClause(
                    "prh.department_name = ANY(:flt_departments)",
                    {"flt_departments": filters.departments},
                )
            )
        if skip != "role" and filters.roles:
            out.append(
                WhereClause("prh.role_title = ANY(:flt_roles)", {"flt_roles": filters.roles})
            )
        if skip != "ids":
            out.append(person_has_identifier_clause("orcid", filters.has_orcid))
            out.append(person_has_identifier_clause("idhal", filters.has_idhal))
            out.append(person_has_identifier_clause("idref", filters.has_idref))
        if skip != "has_rh":
            out.append(person_has_rh_clause(filters.has_rh))
        if skip != "linked":
            out.append(person_linked_clause(filters.linked))
        return out

    # DÉPARTEMENTS
    where_sql, binds = assemble_where(base_clauses(skip="department"))
    dept_rows = (
        await conn.execute(
            text(f"""
                SELECT prh.department_name AS value, COUNT(*) AS count
                FROM {_BASE_FROM}
                WHERE {where_sql} AND prh.department_name IS NOT NULL
                GROUP BY prh.department_name ORDER BY count DESC
            """),
            binds,
        )
    ).all()
    dept_facets = [dict(r._mapping) for r in dept_rows]

    # RÔLES
    where_sql, binds = assemble_where(base_clauses(skip="role"))
    role_rows = (
        await conn.execute(
            text(f"""
                SELECT prh.role_title AS value, COUNT(*) AS count
                FROM {_BASE_FROM}
                WHERE {where_sql} AND prh.role_title IS NOT NULL
                GROUP BY prh.role_title ORDER BY count DESC
            """),
            binds,
        )
    ).all()
    role_facets = [dict(r._mapping) for r in role_rows]

    # ORCID / IDHAL / IDREF — tous skip='ids', donc même WHERE
    where_sql, binds = assemble_where(base_clauses(skip="ids"))
    orcid = (
        await conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'orcid'
                          AND pi.status != 'rejected'
                    )) AS yes,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'orcid'
                          AND pi.status != 'rejected'
                    )) AS no
                FROM {_BASE_FROM} WHERE {where_sql}
            """),
            binds,
        )
    ).one()
    idhal = (
        await conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'idhal'
                          AND pi.status != 'rejected'
                    )) AS yes,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'idhal'
                          AND pi.status != 'rejected'
                    )) AS no
                FROM {_BASE_FROM} WHERE {where_sql}
            """),
            binds,
        )
    ).one()
    idref = (
        await conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'idref'
                          AND pi.status != 'rejected'
                    )) AS yes,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM person_identifiers pi
                        WHERE pi.person_id = p.id AND pi.id_type = 'idref'
                          AND pi.status != 'rejected'
                    )) AS no
                FROM {_BASE_FROM} WHERE {where_sql}
            """),
            binds,
        )
    ).one()

    # RH
    where_sql, binds = assemble_where(base_clauses(skip="has_rh"))
    rh = (
        await conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE prh.id IS NOT NULL) AS yes,
                    COUNT(*) FILTER (WHERE prh.id IS NULL) AS no
                FROM {_BASE_FROM} WHERE {where_sql}
            """),
            binds,
        )
    ).one()

    # LINKED
    where_sql, binds = assemble_where(base_clauses(skip="linked"))
    linked = (
        await conn.execute(
            text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM authorships a WHERE a.person_id = p.id
                    )) AS yes,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM authorships a WHERE a.person_id = p.id
                    )) AS no
                FROM {_BASE_FROM} WHERE {where_sql}
            """),
            binds,
        )
    ).one()

    return {
        "departments": dept_facets,
        "roles": role_facets,
        "orcid": {"yes": orcid.yes, "no": orcid.no},
        "idhal": {"yes": idhal.yes, "no": idhal.no},
        "idref": {"yes": idref.yes, "no": idref.no},
        "rh": {"yes": rh.yes, "no": rh.no},
        "linked": {"yes": linked.yes, "no": linked.no},
    }


# ── Listes de référence ──────────────────────────────────────────


async def list_departments(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Liste des départements distincts."""
    rows = (
        await conn.execute(
            text("""
                SELECT department_name, COUNT(*) AS count
                FROM persons_rh
                WHERE department_name IS NOT NULL
                GROUP BY department_name
                ORDER BY count DESC
            """)
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def list_roles(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Liste des rôles distincts."""
    rows = (
        await conn.execute(
            text("""
                SELECT role_title, COUNT(*) AS count
                FROM persons_rh
                WHERE role_title IS NOT NULL
                GROUP BY role_title
                ORDER BY count DESC
            """)
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def persons_stats(conn: AsyncConnection) -> dict[str, Any]:
    """Statistiques globales personnes."""
    row = (
        await conn.execute(
            text("""
                SELECT
                    (SELECT COUNT(*) FROM persons) AS total_persons,
                    (SELECT COUNT(DISTINCT person_id) FROM authorships
                     WHERE person_id IS NOT NULL) AS linked_persons,
                    (SELECT COUNT(*) FROM authorships
                     WHERE person_id IS NOT NULL) AS linked_authors,
                    (SELECT COUNT(DISTINCT department_name)
                     FROM persons_rh WHERE department_name IS NOT NULL) AS departments
            """)
        )
    ).one()
    return dict(row._mapping)
