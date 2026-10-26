"""Liste des personnes + autocomplete + lecture d'une personne (sync)."""

from sqlalchemy import Connection, Row, text

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
from infrastructure.sql_fragments import GROUP_MEMBERS, has_author_role

# Sous scope `lab_id`, chaque dénombrement se limite aux contributions de la personne rattachées à ce laboratoire, cohérent avec une liste restreinte au labo. Le bind `:flt_person_lab_id` vient de `person_in_lab_clause` (filters.py).
_LAB_SCOPED_CONTRIBUTIONS = (
    " AND EXISTS (SELECT 1 FROM contribution_structures aus "
    "WHERE aus.contribution_id = a.id AND aus.structure_id = :flt_person_lab_id)"
)

# ── Autocomplete ─────────────────────────────────────────────────


def search_persons(conn: Connection, *, search: str, limit: int) -> list[PersonSearchResult]:
    """Recherche rapide (autocomplete) parmi les personnes non exclues, par la règle de l'annuaire (`person_search_clause`)."""
    search_clause = person_search_clause(search)
    if search_clause is None:
        return []
    where_sql, binds = assemble_where([person_exclusion_clause([None]), search_clause])
    rows = conn.execute(
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


# ── Liste admin ──────────────────────────────────────────────────


def _contribution_counts_sql(*, lab_scoped: bool) -> str:
    """Les deux dénombrements de contributions en tant qu'auteur, sous la même condition de scope."""
    scope = _LAB_SCOPED_CONTRIBUTIONS if lab_scoped else ""
    return f"""
        (SELECT COUNT(*) FROM contributions a
         WHERE a.person_id = p.id AND {has_author_role("a")}{scope}) AS contribution_count,
        (SELECT COUNT(*) FROM contributions a
         WHERE a.person_id = p.id AND {has_author_role("a")} AND a.in_perimeter = TRUE{scope}
        ) AS in_perimeter_contribution_count
    """


def list_persons(
    conn: Connection, *, filters: PersonFilters, page: int, per_page: int, sort: str
) -> PersonListResponse:
    """Liste paginée des personnes.

    L'annuaire public et la liste de curation sont deux appels de cette lecture : le premier écarte les personnes rejetées et se scope à un laboratoire, le second garde tout et ajoute les filtres des files à confirmer.
    """
    offset = (page - 1) * per_page
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

    where_sql, binds = assemble_where(clauses)
    order = persons_sort_clause(sort)

    count_row = conn.execute(
        text(
            f"SELECT COUNT(*) AS total FROM persons p "
            f"LEFT JOIN hr_records prh ON prh.person_id = p.id WHERE {where_sql}"
        ),
        binds,
    ).one()
    total = count_row.total

    rows = conn.execute(
        text(f"""
            SELECT p.id, p.last_name, p.first_name,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh, p.exclusion,
                {_contribution_counts_sql(lab_scoped=filters.lab_id is not None)}
            FROM persons p
            LEFT JOIN hr_records prh ON prh.person_id = p.id
            WHERE {where_sql}
            ORDER BY {order}
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {**binds, "pg_limit": per_page, "pg_offset": offset},
    ).all()
    # Tous les identifiants de chaque personne, rejetés compris, avec leur type et leur statut : chaque vue filtre selon ses besoins.
    by_person = person_identifiers(conn, [r.id for r in rows], public_only=False)
    persons = [_person_out(r, by_person.get(r.id, [])) for r in rows]

    return PersonListResponse(total=total, page=page, per_page=per_page, persons=persons)


def _person_out(row: Row[tuple[object, ...]], identifiers: list[PersonIdentifierOut]) -> PersonOut:
    """`PersonOut` d'une ligne de la projection commune à la liste et à `person_curation`."""
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


def person_name_forms(conn: Connection, person_id: int) -> list[NameFormSummaryOut]:
    """Formes de nom d'une personne, avec leur état d'arbitrage.

    Toutes les formes, y compris celles dérivées du nom de la personne (source `persons`). `shared_count` compte les autres personnes qui portent la forme, au sens de `other_name_form_holders`. `publication_count` compte les publications distinctes où un membre d'un groupe de la personne porte la forme.
    """
    rows = conn.execute(
        text(f"""
            SELECT pnf.name_form,
                   pnf.sources,
                   pnf.status::text AS status,
                   (SELECT COUNT(*)
                    FROM ({other_name_form_holders("pnf.name_form", "pnf.person_id")}) holders
                   ) AS shared_count,
                   (SELECT COUNT(DISTINCT g.publication_id)
                    FROM {GROUP_MEMBERS}
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


def person_curation(conn: Connection, person_id: int) -> PersonOut | None:
    """Une personne par id, même projection que la liste. None si absente."""
    row = conn.execute(
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
    by_person = person_identifiers(conn, [row.id], public_only=False)
    return _person_out(row, by_person.get(row.id, []))
