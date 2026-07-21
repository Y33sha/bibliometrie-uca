"""Facettes dynamiques + listes de référence (départements, rôles, stats) — sync."""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.persons_queries import PersonFilters
from infrastructure.queries.api.filters import (
    PUBLIC_PERSON_IDENTIFIER_TYPES_SQL,
    WhereClause,
    assemble_where,
    person_department_clause,
    person_has_identifier_clause,
    person_has_pending_identifiers_clause,
    person_has_pending_name_forms_clause,
    person_has_rh_clause,
    person_in_lab_clause,
    person_rejected_clause,
    person_role_clause,
    person_search_clause,
)

_BASE_FROM = "persons p LEFT JOIN persons_rh prh ON prh.person_id = p.id"


def persons_facets(conn: Connection, *, filters: PersonFilters) -> dict[str, Any]:
    """Facettes dynamiques (chaque facette exclut son propre filtre)."""

    def base_clauses(*, skip: str) -> list[WhereClause | None]:
        # Scope labo, recherche nom et rejet s'appliquent à toutes les facettes : ils
        # délimitent la population décomptée, au lieu d'en être une dimension.
        out: list[WhereClause | None] = [
            person_rejected_clause(filters.rejected),
            person_in_lab_clause(filters.lab_id),
            person_search_clause(filters.search),
        ]
        if skip != "department":
            out.append(person_department_clause(filters.departments))
        if skip != "role":
            out.append(person_role_clause(filters.roles))
        if skip != "ids":
            out.append(person_has_identifier_clause("orcid", filters.has_orcid))
            out.append(person_has_identifier_clause("idhal", filters.has_idhal))
            out.append(person_has_identifier_clause("idref", filters.has_idref))
        if skip != "has_rh":
            out.append(person_has_rh_clause(filters.has_rh))
        if skip != "pending_forms":
            out.append(person_has_pending_name_forms_clause(filters.has_pending_forms))
        if skip != "pending_identifiers":
            out.append(person_has_pending_identifiers_clause(filters.has_pending_identifiers))
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

    # FORMES DE NOM À CONFIRMER (≥1 forme `pending`)
    where_sql, binds = assemble_where(base_clauses(skip="pending_forms"))
    pending_forms = conn.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM person_name_forms pnf
                    WHERE pnf.person_id = p.id AND pnf.status = 'pending'
                )) AS yes,
                COUNT(*) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM person_name_forms pnf
                    WHERE pnf.person_id = p.id AND pnf.status = 'pending'
                )) AS no
            FROM {_BASE_FROM} WHERE {where_sql}
        """),
        binds,
    ).one()

    # IDENTIFIANTS À CONFIRMER (≥1 identifiant public `pending`) — mêmes types
    # que la cellule d'affichage, un `hal_person_id` en attente est interne.
    where_sql, binds = assemble_where(base_clauses(skip="pending_identifiers"))
    pending_identifiers = conn.execute(
        text(f"""
            SELECT
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM person_identifiers pi
                    WHERE pi.person_id = p.id AND pi.status = 'pending'
                      AND pi.id_type IN {PUBLIC_PERSON_IDENTIFIER_TYPES_SQL}
                )) AS yes,
                COUNT(*) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM person_identifiers pi
                    WHERE pi.person_id = p.id AND pi.status = 'pending'
                      AND pi.id_type IN {PUBLIC_PERSON_IDENTIFIER_TYPES_SQL}
                )) AS no
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
        "pending_forms": {"yes": pending_forms.yes, "no": pending_forms.no},
        "pending_identifiers": {"yes": pending_identifiers.yes, "no": pending_identifiers.no},
    }


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
