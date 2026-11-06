"""Facettes de la liste des personnes : catégories de personnel, laboratoires actuels, identifiants, fiche RH, éléments à confirmer."""

from sqlalchemy import Connection, text

from infrastructure.read_models._common import FacetOption, YesNoCount
from infrastructure.read_models.filters import (
    PERSON_HAS_PENDING_IDENTIFIERS_SQL,
    PERSON_HAS_PENDING_NAME_FORMS_SQL,
    WhereClause,
    assemble_where,
    person_active_clause,
    person_category_clause,
    person_exclusion_clause,
    person_has_identifier_clause,
    person_has_identifier_sql,
    person_has_pending_identifiers_clause,
    person_has_pending_name_forms_clause,
    person_has_rh_clause,
    person_in_lab_clause,
    person_laboratory_clause,
    person_search_clause,
)
from infrastructure.read_models.persons.models import (
    PersonFilters,
    PersonsFacetsResponse,
)
from infrastructure.read_models.sql_fragments import current_hr_period

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
            if skip != "category":
                out.append(person_category_clause(filters.categories))
            if skip != "laboratory":
                out.append(person_laboratory_clause(filters.laboratories))
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

        def hr_record_facet(column: str, skip: str) -> list[FacetOption]:
            where_sql, binds = assemble_where(base_clauses(skip=skip))
            rows = self._conn.execute(
                text(f"""
                    SELECT prh.{column} AS value, COUNT(*) AS n
                    FROM {_BASE_FROM}
                    WHERE {where_sql} AND prh.{column} IS NOT NULL
                    GROUP BY prh.{column} ORDER BY n DESC
                """),
                binds,
            ).all()
            return [FacetOption(value=r.value, count=r.n) for r in rows]

        # LABORATOIRES ACTUELS
        where_sql, binds = assemble_where(base_clauses(skip="laboratory"))
        lab_rows = self._conn.execute(
            text(f"""
                SELECT s.id, coalesce(s.acronym, s.name) AS label, COUNT(DISTINCT p.id) AS n
                FROM {_BASE_FROM}
                JOIN hr_periods hp ON hp.person_id = p.id AND {current_hr_period("hp")}
                JOIN structures s ON s.id = hp.structure_id
                WHERE {where_sql}
                GROUP BY s.id, label ORDER BY n DESC, label
            """),
            binds,
        ).all()
        lab_facets = [FacetOption(value=str(r.id), label=r.label, count=r.n) for r in lab_rows]

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
            categories=hr_record_facet("staff_category", "category"),
            laboratories=lab_facets,
            orcid=YesNoCount(yes=ids.orcid_yes, no=ids.orcid_no),
            idhal=YesNoCount(yes=ids.idhal_yes, no=ids.idhal_no),
            idref=YesNoCount(yes=ids.idref_yes, no=ids.idref_no),
            rh=YesNoCount(yes=rh.yes, no=rh.no),
            pending_forms=YesNoCount(yes=pending_forms.yes, no=pending_forms.no),
            pending_identifiers=YesNoCount(yes=pending_identifiers.yes, no=pending_identifiers.no),
        )
