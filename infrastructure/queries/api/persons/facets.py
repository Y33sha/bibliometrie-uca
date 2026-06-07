"""Facettes dynamiques + listes de référence (départements, rôles, stats) — sync."""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.persons_queries import FacetFilters
from infrastructure.queries.filters import (
    WhereClause,
    assemble_where,
    person_has_identifier_clause,
    person_has_rh_clause,
    person_in_lab_clause,
)

_BASE_FROM = "persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id"


def persons_facets(conn: Connection, *, filters: FacetFilters) -> dict[str, Any]:
    """Facettes dynamiques (chaque facette exclut son propre filtre)."""

    def base_clauses(*, skip: str) -> list[WhereClause | None]:
        # Le scope labo n'est pas une facette : il s'applique toujours.
        out: list[WhereClause | None] = [person_in_lab_clause(filters.lab_id)]
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
        return out

    # DÉPARTEMENTS
    where_sql, binds = assemble_where(base_clauses(skip="department"))
    dept_rows = conn.execute(
        text(f"""
            SELECT prh.department_name AS value, COUNT(*) AS count
            FROM {_BASE_FROM}
            WHERE {where_sql} AND prh.department_name IS NOT NULL
            GROUP BY prh.department_name ORDER BY count DESC
        """),
        binds,
    ).all()
    dept_facets = [dict(r._mapping) for r in dept_rows]

    # RÔLES
    where_sql, binds = assemble_where(base_clauses(skip="role"))
    role_rows = conn.execute(
        text(f"""
            SELECT prh.role_title AS value, COUNT(*) AS count
            FROM {_BASE_FROM}
            WHERE {where_sql} AND prh.role_title IS NOT NULL
            GROUP BY prh.role_title ORDER BY count DESC
        """),
        binds,
    ).all()
    role_facets = [dict(r._mapping) for r in role_rows]

    # ORCID / IDHAL / IDREF — tous skip='ids', donc même WHERE
    where_sql, binds = assemble_where(base_clauses(skip="ids"))
    orcid = conn.execute(
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
    ).one()
    idhal = conn.execute(
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
    ).one()
    idref = conn.execute(
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
    ).one()

    # RH
    where_sql, binds = assemble_where(base_clauses(skip="has_rh"))
    rh = conn.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE prh.id IS NOT NULL) AS yes,
                COUNT(*) FILTER (WHERE prh.id IS NULL) AS no
            FROM {_BASE_FROM} WHERE {where_sql}
        """),
        binds,
    ).one()

    return {
        "departments": dept_facets,
        "roles": role_facets,
        "orcid": {"yes": orcid.yes, "no": orcid.no},
        "idhal": {"yes": idhal.yes, "no": idhal.no},
        "idref": {"yes": idref.yes, "no": idref.no},
        "rh": {"yes": rh.yes, "no": rh.no},
    }


# ── Listes de référence ──────────────────────────────────────────


def list_departments(conn: Connection) -> list[dict[str, Any]]:
    """Liste des départements distincts."""
    rows = conn.execute(
        text("""
            SELECT department_name, COUNT(*) AS count
            FROM persons_rh
            WHERE department_name IS NOT NULL
            GROUP BY department_name
            ORDER BY count DESC
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def list_roles(conn: Connection) -> list[dict[str, Any]]:
    """Liste des rôles distincts."""
    rows = conn.execute(
        text("""
            SELECT role_title, COUNT(*) AS count
            FROM persons_rh
            WHERE role_title IS NOT NULL
            GROUP BY role_title
            ORDER BY count DESC
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def persons_stats(conn: Connection) -> dict[str, Any]:
    """Statistiques globales personnes."""
    row = conn.execute(
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
    ).one()
    return dict(row._mapping)
