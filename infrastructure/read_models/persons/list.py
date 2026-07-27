"""Liste des personnes + autocomplete + lecture d'une personne (sync)."""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.read_models.persons_queries import (
    NameFormSummaryOut,
    PersonFilters,
    PersonIdentifierOut,
    PersonListResponse,
    PersonOut,
    PersonSearchResult,
)
from domain.sources.registry import AUTHOR_SOURCES
from infrastructure.db.sql_fragments import in_clause
from infrastructure.read_models.filters import (
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
    persons_sort_clause,
)
from infrastructure.read_models.persons.identifiers import public_identifiers

# Sous scope `lab_id`, chaque dénombrement se limite aux signatures de la personne rattachées à ce laboratoire, cohérent avec une liste restreinte au labo. Le bind `:flt_person_lab_id` vient de `person_in_lab_clause` (filters.py).
_LAB_SCOPED_SIGNATURES = (
    " AND EXISTS (SELECT 1 FROM authorship_structures aus "
    "WHERE aus.authorship_id = a.id AND aus.structure_id = :flt_person_lab_id)"
)

# ── Autocomplete ─────────────────────────────────────────────────


def search_persons(conn: Connection, *, search: str, limit: int) -> list[PersonSearchResult]:
    """Recherche rapide (autocomplete) : chaque mot doit matcher dans last ou first name."""
    words = search.strip().split()
    if not words:
        return []
    clauses: list[WhereClause | None] = [WhereClause("p.rejected = FALSE", {})]
    for i, w in enumerate(words):
        key = f"search_word_{i}"
        clauses.append(
            WhereClause(
                f"(unaccent(p.last_name) ILIKE unaccent(:{key}) "
                f"OR unaccent(p.first_name) ILIKE unaccent(:{key}))",
                {key: f"%{w}%"},
            )
        )
    where_sql, binds = assemble_where(clauses)
    rows = conn.execute(
        text(f"""
            SELECT p.id, p.last_name, p.first_name, prh.department_name,
                   (prh.id IS NOT NULL) AS has_rh
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
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


def _signature_counts_sql(*, lab_scoped: bool) -> str:
    """Les trois dénombrements de signatures, sous la même condition de scope."""
    scope = _LAB_SCOPED_SIGNATURES if lab_scoped else ""
    return f"""
        (SELECT COUNT(*) FROM authorships a
         WHERE a.person_id = p.id{scope}) AS signature_count,
        (SELECT COUNT(*) FROM authorships a
         WHERE a.person_id = p.id AND a.roles && ARRAY['author']::text[]{scope}
        ) AS signature_count_as_author,
        (SELECT COUNT(*) FROM authorships a
         WHERE a.person_id = p.id AND a.in_perimeter = TRUE{scope}
        ) AS in_perimeter_signature_count
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
        person_rejected_clause(filters.rejected),
        person_in_lab_clause(filters.lab_id),
    ]

    where_sql, binds = assemble_where(clauses)
    order = persons_sort_clause(sort)

    count_row = conn.execute(
        text(
            f"SELECT COUNT(*) AS total FROM persons p "
            f"LEFT JOIN persons_rh prh ON prh.person_id = p.id WHERE {where_sql}"
        ),
        binds,
    ).one()
    total = count_row.total

    rows = conn.execute(
        text(f"""
            SELECT p.id, p.last_name, p.first_name,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh, p.rejected,
                {_signature_counts_sql(lab_scoped=filters.lab_id is not None)}
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE {where_sql}
            ORDER BY {order}
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {**binds, "pg_limit": per_page, "pg_offset": offset},
    ).all()
    # Identifiants attachés à chaque personne, rejetés compris : chaque identifiant porte son statut, à charge pour chaque vue de filtrer selon ses besoins.
    by_person = public_identifiers(conn, [r.id for r in rows], include_rejected=True)
    persons = [_person_out(r, by_person.get(r.id, [])) for r in rows]

    return PersonListResponse(total=total, page=page, per_page=per_page, persons=persons)


def _person_out(row: Any, identifiers: list[PersonIdentifierOut]) -> PersonOut:
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
        rejected=row.rejected,
        signature_count=row.signature_count,
        signature_count_as_author=row.signature_count_as_author,
        in_perimeter_signature_count=row.in_perimeter_signature_count,
        identifiers=identifiers,
    )


def person_name_forms(conn: Connection, person_id: int) -> list[NameFormSummaryOut]:
    """Formes de nom d'une personne, avec leur état d'arbitrage.

    Toutes les formes, y compris celles entièrement dérivées du nom canonique (source `persons` seule) : la fiche d'une personne les présente à la curation. `shared_count` compte les personnes qui portent la même forme, `ambiguous` dit qu'elles sont plusieurs, et `pub_count` les publications distinctes que la forme signe.
    """
    rows = conn.execute(
        text(f"""
            SELECT pnf.name_form,
                   pnf.sources,
                   pnf.status::text AS status,
                   (SELECT COUNT(*) FROM person_name_forms p2
                    WHERE p2.name_form = pnf.name_form) AS shared_count,
                   (SELECT COUNT(*) > 1 FROM person_name_forms p2
                    WHERE p2.name_form = pnf.name_form) AS ambiguous,
                   (SELECT COUNT(DISTINCT sd.publication_id)
                    FROM source_authorships sa
                    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    WHERE sa.person_id = pnf.person_id
                      AND aik.author_name_normalized = pnf.name_form
                      AND sa.source IN {in_clause(AUTHOR_SOURCES)}
                   ) AS pub_count
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
            ambiguous=r.ambiguous,
            status=r.status,
            shared_count=r.shared_count,
            pub_count=r.pub_count,
        )
        for r in rows
    ]


def person_curation(conn: Connection, person_id: int) -> PersonOut | None:
    """Une personne par id, même projection que la liste. None si absente."""
    row = conn.execute(
        text(f"""
            SELECT p.id, p.last_name, p.first_name,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh, p.rejected,
                {_signature_counts_sql(lab_scoped=False)}
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id = :id
        """),
        {"id": person_id},
    ).one_or_none()
    if row is None:
        return None
    by_person = public_identifiers(conn, [row.id], include_rejected=True)
    return _person_out(row, by_person.get(row.id, []))
