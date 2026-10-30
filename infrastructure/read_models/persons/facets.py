"""Facettes de la liste des personnes : départements, rôles, identifiants, fiche RH, éléments à confirmer."""

from sqlalchemy import Connection, text

from infrastructure.read_models._common import FacetOption, YesNoCount
from infrastructure.read_models.filters import (
    PERSON_HAS_PENDING_IDENTIFIERS_SQL,
    PERSON_HAS_PENDING_NAME_FORMS_SQL,
    WhereClause,
    assemble_where,
    person_active_clause,
    person_department_clause,
    person_exclusion_clause,
    person_has_identifier_clause,
    person_has_identifier_sql,
    person_has_pending_identifiers_clause,
    person_has_pending_name_forms_clause,
    person_has_rh_clause,
    person_in_lab_clause,
    person_role_clause,
    person_search_clause,
)
from infrastructure.read_models.persons.models import (
    PersonFilters,
    PersonsFacetsResponse,
)

_BASE_FROM = "persons p LEFT JOIN hr_records prh ON prh.person_id = p.id"


def _yesno(predicate: str, prefix: str = "") -> str:
    """Renvoie le fragment SELECT comptant les personnes vérifiant `predicate` (`{prefix}yes`) et les autres (`{prefix}no`)."""
    return (
        f"COUNT(*) FILTER (WHERE {predicate}) AS {prefix}yes, "
        f"COUNT(*) FILTER (WHERE NOT ({predicate})) AS {prefix}no"
    )


class PersonFacetQueries:
    _conn: Connection

    def persons_facets(self, *, filters: PersonFilters) -> PersonsFacetsResponse:
        """Renvoie les facettes dynamiques ; chaque facette exclut son propre filtre."""

        def base_clauses(*, skip: str) -> list[WhereClause | None]:
            # Laboratoire, recherche par nom, exclusion et activité délimitent la population décomptée : ils valent pour toutes les facettes. Chaque autre filtre est exclu de sa propre facette.
            out: list[WhereClause | None] = [
                person_exclusion_clause(filters.exclusions),
                person_active_clause(filters.active),
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
        dept_rows = self._conn.execute(
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
        role_rows = self._conn.execute(
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
        ids = self._conn.execute(
            text(f"""
                SELECT {_yesno(person_has_identifier_sql("orcid"), "orcid_")},
                       {_yesno(person_has_identifier_sql("idhal"), "idhal_")},
                       {_yesno(person_has_identifier_sql("idref"), "idref_")}
                FROM {_BASE_FROM} WHERE {where_sql}
            """),
            binds,
        ).one()

        # RH
        where_sql, binds = assemble_where(base_clauses(skip="has_rh"))
        rh = self._conn.execute(
            text(f"SELECT {_yesno('prh.id IS NOT NULL')} FROM {_BASE_FROM} WHERE {where_sql}"),
            binds,
        ).one()

        # FORMES DE NOM À CONFIRMER (au moins une forme en attente)
        where_sql, binds = assemble_where(base_clauses(skip="pending_forms"))
        pending_forms = self._conn.execute(
            text(
                f"SELECT {_yesno(PERSON_HAS_PENDING_NAME_FORMS_SQL)} FROM {_BASE_FROM} WHERE {where_sql}"
            ),
            binds,
        ).one()

        # IDENTIFIANTS À CONFIRMER
        where_sql, binds = assemble_where(base_clauses(skip="pending_identifiers"))
        pending_identifiers = self._conn.execute(
            text(
                f"SELECT {_yesno(PERSON_HAS_PENDING_IDENTIFIERS_SQL)} FROM {_BASE_FROM} WHERE {where_sql}"
            ),
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
