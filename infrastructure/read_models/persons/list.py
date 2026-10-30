"""Liste des personnes, autocomplétion et lecture d'une personne."""

from collections.abc import Iterator

from sqlalchemy import Connection, Row, text

from infrastructure.read_models.csv_export import csv_chunks, fetch_export_rows
from infrastructure.read_models.filters import (
    WhereClause,
    assemble_where,
    person_active_clause,
    person_department_clause,
    person_exclusion_clause,
    person_has_identifier_clause,
    person_has_pending_identifiers_clause,
    person_has_pending_name_forms_clause,
    person_has_rh_clause,
    person_in_lab_clause,
    person_role_clause,
    person_search_clause,
    persons_sort_clause,
)
from infrastructure.read_models.persons.identifiers import person_identifiers
from infrastructure.read_models.persons.models import (
    NameFormSummaryOut,
    PersonFilters,
    PersonIdentifierOut,
    PersonListResponse,
    PersonOut,
    PersonSearchResult,
)
from infrastructure.read_models.sql_fragments import other_name_form_holders
from infrastructure.sql_fragments import CONTRIBUTIONS_AND_SOURCES, has_author_role

# Avec `lab_id`, chaque dénombrement se limite aux contributions de la personne rattachées à ce laboratoire, comme la liste. Le paramètre `:flt_person_lab_id` vient de `person_in_lab_clause`.
_LAB_SCOPED_CONTRIBUTIONS = (
    " AND EXISTS (SELECT 1 FROM contribution_structures aus "
    "WHERE aus.contribution_id = a.id AND aus.structure_id = :flt_person_lab_id)"
)


def _contribution_counts_sql(*, lab_scoped: bool) -> str:
    """Renvoie les deux dénombrements de contributions d'auteur, sous la même restriction au laboratoire."""
    scope = _LAB_SCOPED_CONTRIBUTIONS if lab_scoped else ""
    return f"""
        (SELECT COUNT(*) FROM contributions a
         WHERE a.person_id = p.id AND {has_author_role("a")}{scope}) AS contribution_count,
        (SELECT COUNT(*) FROM contributions a
         WHERE a.person_id = p.id AND {has_author_role("a")} AND a.in_perimeter = TRUE{scope}
        ) AS in_perimeter_contribution_count
    """


def _person_where(filters: PersonFilters) -> tuple[str, dict[str, object]]:
    """Renvoie la clause WHERE de la liste des personnes, sur les alias `p` (`persons`) et `prh` (`hr_records`)."""
    clauses: list[WhereClause | None] = [
        person_search_clause(filters.search),
        person_department_clause(filters.departments),
        person_role_clause(filters.roles),
        person_has_identifier_clause("orcid", filters.has_orcid),
        person_has_identifier_clause("idhal", filters.has_idhal),
        person_has_identifier_clause("idref", filters.has_idref),
        person_has_rh_clause(filters.has_rh),
        person_has_pending_name_forms_clause(filters.has_pending_forms),
        person_has_pending_identifiers_clause(filters.has_pending_identifiers),
        person_exclusion_clause(filters.exclusions),
        person_active_clause(filters.active),
        person_in_lab_clause(filters.lab_id),
    ]
    return assemble_where(clauses)


def _list_sql(filters: PersonFilters, where_sql: str, sort: str) -> str:
    """Renvoie la requête triée de la liste des personnes, sans pagination."""
    return f"""
        SELECT p.id, p.last_name, p.first_name,
            prh.role_title, prh.department_name, prh.start_date, prh.end_date,
            (prh.id IS NOT NULL) AS has_rh, p.exclusion,
            {_contribution_counts_sql(lab_scoped=filters.lab_id is not None)}
        FROM persons p
        LEFT JOIN hr_records prh ON prh.person_id = p.id
        WHERE {where_sql}
        ORDER BY {persons_sort_clause(sort)}
    """


def _person_out(row: Row[tuple[object, ...]], identifiers: list[PersonIdentifierOut]) -> PersonOut:
    """Construit le `PersonOut` d'une ligne de la projection commune à la liste et à `person_curation`."""
    return PersonOut(
        id=row.id,
        last_name=row.last_name,
        first_name=row.first_name,
        role_title=row.role_title,
        department_name=row.department_name,
        start_date=row.start_date,
        end_date=row.end_date,
        has_rh=row.has_rh,
        exclusion=row.exclusion,
        contribution_count=row.contribution_count,
        in_perimeter_contribution_count=row.in_perimeter_contribution_count,
        identifiers=identifiers,
    )


class PersonListQueries:
    _conn: Connection

    def search_persons(self, *, search: str, limit: int) -> list[PersonSearchResult]:
        """Renvoie, pour l'autocomplétion, les personnes non exclues trouvées par la recherche par nom de l'annuaire (`person_search_clause`)."""
        search_clause = person_search_clause(search)
        if search_clause is None:
            return []
        where_sql, binds = assemble_where([person_exclusion_clause([None]), search_clause])
        rows = self._conn.execute(
            text(f"""
                SELECT p.id, p.last_name, p.first_name, prh.department_name,
                       (prh.id IS NOT NULL) AS has_rh
                FROM persons p
                LEFT JOIN hr_records prh ON prh.person_id = p.id
                WHERE {where_sql}
                ORDER BY LOWER(p.last_name), LOWER(p.first_name)
                LIMIT :pg_limit
            """),
            {**binds, "pg_limit": limit},
        ).all()
        return [
            PersonSearchResult(
                id=r.id,
                last_name=r.last_name,
                first_name=r.first_name,
                department_name=r.department_name,
                has_rh=r.has_rh,
            )
            for r in rows
        ]

    def list_persons(
        self, *, filters: PersonFilters, page: int, per_page: int, sort: str
    ) -> PersonListResponse:
        """Renvoie la liste paginée des personnes.

        L'annuaire public et la liste d'administration appellent tous deux cette lecture. L'annuaire écarte les personnes exclues et se restreint à un laboratoire. La liste d'administration garde tout et ajoute les filtres des files à confirmer.
        """
        offset = (page - 1) * per_page
        where_sql, binds = _person_where(filters)

        count_row = self._conn.execute(
            text(
                f"SELECT COUNT(*) AS total FROM persons p "
                f"LEFT JOIN hr_records prh ON prh.person_id = p.id WHERE {where_sql}"
            ),
            binds,
        ).one()
        total = count_row.total

        rows = self._conn.execute(
            text(f"{_list_sql(filters, where_sql, sort)} LIMIT :pg_limit OFFSET :pg_offset"),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        # Tous les identifiants de chaque personne, rejetés compris, avec leur type et leur statut : chaque vue filtre selon ses besoins.
        by_person = person_identifiers(self._conn, [r.id for r in rows], public_only=False)
        persons = [_person_out(r, by_person.get(r.id, [])) for r in rows]

        return PersonListResponse(total=total, page=page, per_page=per_page, persons=persons)

    def export_persons_csv(self, *, filters: PersonFilters, sort: str) -> Iterator[str]:
        """Renvoie l'export CSV de la liste des personnes, aux filtres et au tri de la liste.

        Les identifiants exportés sont ceux de l'annuaire public : ORCID, idHAL et IdRef, sans les attributions rejetées. La requête s'exécute à l'appel. Le parcours qui suit lit des lignes en mémoire.
        """
        where_sql, binds = _person_where(filters)
        rows, truncated = fetch_export_rows(
            self._conn, _list_sql(filters, where_sql, sort), binds, name="personnes"
        )
        by_person = person_identifiers(self._conn, [r.id for r in rows], public_only=True)

        def values(person_id: int, id_type: str) -> str:
            found = {i.id_value for i in by_person.get(person_id, []) if i.id_type == id_type}
            return " ".join(sorted(found))

        return csv_chunks(
            [
                "Nom",
                "Prénom",
                "RH",
                "ORCID",
                "idHAL",
                "IdRef",
                "Fonction",
                "Département",
                "Publications",
            ],
            (
                [
                    r.last_name,
                    r.first_name,
                    "oui" if r.has_rh else "",
                    values(r.id, "orcid"),
                    values(r.id, "idhal"),
                    values(r.id, "idref"),
                    r.role_title or "",
                    r.department_name or "",
                    r.contribution_count,
                ]
                for r in rows
            ),
            truncated=truncated,
        )

    def person_name_forms(self, person_id: int) -> list[NameFormSummaryOut]:
        """Renvoie toutes les formes de nom d'une personne, avec leur état d'arbitrage, y compris les formes dérivées de son nom (source `persons`).

        `shared_count` compte les autres personnes ayant la forme, au sens de `other_name_form_holders`. `publication_count` compte les publications distinctes où une contribution source d'une contribution de la personne a cette forme.
        """
        rows = self._conn.execute(
            text(f"""
                SELECT pnf.name_form,
                       pnf.sources,
                       pnf.status::text AS status,
                       (SELECT COUNT(*)
                        FROM ({other_name_form_holders("pnf.name_form", "pnf.person_id")}) holders
                       ) AS shared_count,
                       (SELECT COUNT(DISTINCT g.publication_id)
                        FROM {CONTRIBUTIONS_AND_SOURCES}
                        WHERE g.person_id = pnf.person_id
                          AND ci.author_name_normalized = pnf.name_form
                       ) AS publication_count
                FROM person_name_forms pnf
                WHERE pnf.person_id = :pid
                ORDER BY pnf.name_form
            """),
            {"pid": person_id},
        ).all()
        return [
            NameFormSummaryOut(
                name_form=r.name_form,
                sources=r.sources,
                status=r.status,
                shared_count=r.shared_count,
                publication_count=r.publication_count,
            )
            for r in rows
        ]

    def person_curation(self, person_id: int) -> PersonOut | None:
        """Renvoie une personne par id, avec la projection de la liste, ou `None` si elle est absente."""
        row = self._conn.execute(
            text(f"""
                SELECT p.id, p.last_name, p.first_name,
                    prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                    (prh.id IS NOT NULL) AS has_rh, p.exclusion,
                    {_contribution_counts_sql(lab_scoped=False)}
                FROM persons p
                LEFT JOIN hr_records prh ON prh.person_id = p.id
                WHERE p.id = :id
            """),
            {"id": person_id},
        ).one_or_none()
        if row is None:
            return None
        by_person = person_identifiers(self._conn, [row.id], public_only=False)
        return _person_out(row, by_person.get(row.id, []))
