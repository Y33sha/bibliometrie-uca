"""Facettes dynamiques + listes de référence (départements, rôles, stats)."""

from sqlalchemy import Connection, text

from application.ports.api._common import FacetOption, YesNoCount
from application.ports.api.persons_queries import (
    PersonFilters,
    PersonsFacetsResponse,
    PersonsStatsResponse,
)
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


def _yesno(predicate: str, prefix: str = "") -> str:
    """Fragment SELECT comptant les personnes qui vérifient `predicate` (`{prefix}yes`) et les autres (`{prefix}no`)."""
    return (
        f"COUNT(*) FILTER (WHERE {predicate}) AS {prefix}yes, "
        f"COUNT(*) FILTER (WHERE NOT ({predicate})) AS {prefix}no"
    )


def _has_identifier(id_type: str) -> str:
    """Prédicat : la personne `p` porte un identifiant `id_type` au statut hors 'rejected'."""
    return (
        "EXISTS (SELECT 1 FROM person_identifiers pi "
        f"WHERE pi.person_id = p.id AND pi.id_type = '{id_type}' AND pi.status != 'rejected')"
    )


def persons_facets(conn: Connection, *, filters: PersonFilters) -> PersonsFacetsResponse:
    """Facettes dynamiques (chaque facette exclut son propre filtre)."""

    def base_clauses(*, skip: str) -> list[WhereClause | None]:
        # Scope labo, recherche nom et rejet délimitent la population décomptée : ils s'appliquent à toutes les facettes, quand les autres filtres sont chacun exclu de leur propre facette.
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
            SELECT prh.department_name AS value, COUNT(*) AS n
            FROM {_BASE_FROM}
            WHERE {where_sql} AND prh.department_name IS NOT NULL
            GROUP BY prh.department_name ORDER BY n DESC
        """),
        binds,
    ).all()
    dept_facets = [FacetOption(value=r.value, count=r.n) for r in dept_rows]

    # RÔLES
    where_sql, binds = assemble_where(base_clauses(skip="role"))
    role_rows = conn.execute(
        text(f"""
            SELECT prh.role_title AS value, COUNT(*) AS n
            FROM {_BASE_FROM}
            WHERE {where_sql} AND prh.role_title IS NOT NULL
            GROUP BY prh.role_title ORDER BY n DESC
        """),
        binds,
    ).all()
    role_facets = [FacetOption(value=r.value, count=r.n) for r in role_rows]

    # ORCID / IDHAL / IDREF partagent la population (skip='ids') : un seul passage.
    where_sql, binds = assemble_where(base_clauses(skip="ids"))
    ids = conn.execute(
        text(f"""
            SELECT {_yesno(_has_identifier("orcid"), "orcid_")},
                   {_yesno(_has_identifier("idhal"), "idhal_")},
                   {_yesno(_has_identifier("idref"), "idref_")}
            FROM {_BASE_FROM} WHERE {where_sql}
        """),
        binds,
    ).one()

    # RH
    where_sql, binds = assemble_where(base_clauses(skip="has_rh"))
    rh = conn.execute(
        text(f"SELECT {_yesno('prh.id IS NOT NULL')} FROM {_BASE_FROM} WHERE {where_sql}"),
        binds,
    ).one()

    # FORMES DE NOM À CONFIRMER (≥1 forme `pending`)
    where_sql, binds = assemble_where(base_clauses(skip="pending_forms"))
    pending_forms_pred = (
        "EXISTS (SELECT 1 FROM person_name_forms pnf "
        "WHERE pnf.person_id = p.id AND pnf.status = 'pending')"
    )
    pending_forms = conn.execute(
        text(f"SELECT {_yesno(pending_forms_pred)} FROM {_BASE_FROM} WHERE {where_sql}"),
        binds,
    ).one()

    # IDENTIFIANTS À CONFIRMER (≥1 identifiant public `pending`) — mêmes types que la cellule d'affichage, un `hal_person_id` en attente est interne.
    where_sql, binds = assemble_where(base_clauses(skip="pending_identifiers"))
    pending_ids_pred = (
        "EXISTS (SELECT 1 FROM person_identifiers pi "
        "WHERE pi.person_id = p.id AND pi.status = 'pending' "
        f"AND pi.id_type IN {PUBLIC_PERSON_IDENTIFIER_TYPES_SQL})"
    )
    pending_identifiers = conn.execute(
        text(f"SELECT {_yesno(pending_ids_pred)} FROM {_BASE_FROM} WHERE {where_sql}"),
        binds,
    ).one()

    return PersonsFacetsResponse(
        departments=dept_facets,
        roles=role_facets,
        orcid=YesNoCount(yes=ids.orcid_yes, no=ids.orcid_no),
        idhal=YesNoCount(yes=ids.idhal_yes, no=ids.idhal_no),
        idref=YesNoCount(yes=ids.idref_yes, no=ids.idref_no),
        rh=YesNoCount(yes=rh.yes, no=rh.no),
        pending_forms=YesNoCount(yes=pending_forms.yes, no=pending_forms.no),
        pending_identifiers=YesNoCount(yes=pending_identifiers.yes, no=pending_identifiers.no),
    )


def persons_stats(conn: Connection) -> PersonsStatsResponse:
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
    return PersonsStatsResponse(
        total_persons=row.total_persons,
        linked_persons=row.linked_persons,
        linked_authors=row.linked_authors,
        departments=row.departments,
    )
