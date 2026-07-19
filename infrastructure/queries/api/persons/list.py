"""Annuaire public + autocomplete + liste admin des personnes (sync)."""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.persons_queries import DirectoryFilters, ListFilters
from infrastructure.queries.api.persons.identifiers import public_identifiers
from infrastructure.queries.filters import (
    WhereClause,
    assemble_where,
    person_department_clause,
    person_has_identifier_clause,
    person_has_pending_identifiers_clause,
    person_has_pending_name_forms_clause,
    person_has_rh_clause,
    person_in_lab_clause,
    person_role_clause,
    person_search_clause,
    persons_sort_clause,
)
from infrastructure.queries.sources_sql import AUTHOR_SOURCES_SQL

# ── Annuaire public ──────────────────────────────────────────────


def persons_directory(
    conn: Connection, *, filters: DirectoryFilters, page: int, per_page: int, sort: str
) -> dict[str, Any]:
    """Annuaire public des personnes avec ORCID et idHAL."""
    offset = (page - 1) * per_page
    clauses: list[WhereClause | None] = [WhereClause("p.rejected = FALSE", {})]
    clauses.append(person_search_clause(filters.search))
    clauses.append(person_department_clause(filters.departments))
    clauses.append(person_role_clause(filters.roles))
    clauses.append(person_has_identifier_clause("orcid", filters.has_orcid))
    clauses.append(person_has_identifier_clause("idhal", filters.has_idhal))
    clauses.append(person_has_identifier_clause("idref", filters.has_idref))
    clauses.append(person_has_rh_clause(filters.has_rh))
    clauses.append(person_in_lab_clause(filters.lab_id))

    where_sql, binds = assemble_where(clauses)
    order = persons_sort_clause(sort)

    # En contexte labo, le décompte est scopé aux publications du labo (cohérent
    # avec le filtre `lab_id`) ; sinon c'est le total global de la personne.
    pub_count_lab_filter = (
        " AND EXISTS (SELECT 1 FROM authorship_structures aus "
        "WHERE aus.authorship_id = a.id AND aus.structure_id = :flt_person_lab_id)"
        if filters.lab_id
        else ""
    )

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
            SELECT
                p.id, p.last_name, p.first_name,
                prh.role_title, prh.department_name,
                (prh.id IS NOT NULL) AS has_rh,
                (SELECT COUNT(DISTINCT a.publication_id)
                 FROM authorships a
                 WHERE a.person_id = p.id AND a.roles && ARRAY['author']::text[]
                 {pub_count_lab_filter}
                ) AS signature_count_as_author
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE {where_sql}
            ORDER BY {order}
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {**binds, "pg_limit": per_page, "pg_offset": offset},
    ).all()
    persons_rows = [dict(r._mapping) for r in rows]
    _attach_identifiers(conn, persons_rows, include_rejected=False)

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "persons": persons_rows,
    }


# ── Autocomplete ─────────────────────────────────────────────────


def search_persons(conn: Connection, *, q: str, limit: int) -> list[dict[str, Any]]:
    """Recherche rapide (autocomplete) : chaque mot doit matcher dans last ou first name."""
    words = q.strip().split()
    if not words:
        return []
    clauses: list[WhereClause | None] = [WhereClause("p.rejected = FALSE", {})]
    for i, w in enumerate(words):
        key = f"q_word_{i}"
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
    return [dict(r._mapping) for r in rows]


# ── Liste admin ──────────────────────────────────────────────────


_LIST_SORT_MAP = {
    "name_asc": "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC",
    "name_desc": "LOWER(p.last_name) DESC, LOWER(p.first_name) DESC",
    "signatures_asc": "signature_count ASC, LOWER(p.last_name) ASC",
    "signatures_desc": "signature_count DESC, LOWER(p.last_name) ASC",
    "in_perimeter_signatures_asc": "in_perimeter_signature_count ASC, LOWER(p.last_name) ASC",
    "in_perimeter_signatures_desc": "in_perimeter_signature_count DESC, LOWER(p.last_name) ASC",
}


def list_persons(
    conn: Connection, *, filters: ListFilters, page: int, per_page: int, sort: str
) -> dict[str, Any]:
    """Liste des personnes avec filtres (admin)."""
    offset = (page - 1) * per_page
    clauses: list[WhereClause | None] = []

    clauses.append(person_search_clause(filters.search))
    clauses.append(person_department_clause(filters.departments))
    clauses.append(person_role_clause(filters.roles))
    clauses.append(person_has_identifier_clause("orcid", filters.has_orcid))
    clauses.append(person_has_identifier_clause("idhal", filters.has_idhal))
    clauses.append(person_has_identifier_clause("idref", filters.has_idref))
    clauses.append(person_has_rh_clause(filters.has_rh))
    clauses.append(person_has_pending_name_forms_clause(filters.has_pending_forms))
    clauses.append(person_has_pending_identifiers_clause(filters.has_pending_identifiers))

    where_sql, binds = assemble_where(clauses)
    order = _LIST_SORT_MAP[sort]

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
                p.last_name_normalized, p.first_name_normalized,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh, p.rejected,
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id) AS signature_count,
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id AND a.in_perimeter = TRUE)
                    AS in_perimeter_signature_count
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE {where_sql}
            ORDER BY {order}
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {**binds, "pg_limit": per_page, "pg_offset": offset},
    ).all()
    persons_rows = [dict(r._mapping) for r in rows]
    _attach_identifiers(conn, persons_rows, include_rejected=True)

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "persons": persons_rows,
    }


def _attach_identifiers(
    conn: Connection, persons_rows: list[dict[str, Any]], *, include_rejected: bool
) -> None:
    """Enrichit en place chaque ligne personne avec ses identifiants.

    Les formes de nom ne suivent pas : seule la fiche d'une personne les affiche, et les porter par ligne pesait les deux tiers de la liste (`person_name_forms` par `PgPersonsQueries.person_name_forms`).
    """
    by_person = public_identifiers(
        conn, [p["id"] for p in persons_rows], include_rejected=include_rejected
    )
    for p in persons_rows:
        p["identifiers"] = by_person.get(p["id"], [])


def person_name_forms(conn: Connection, person_id: int) -> list[dict[str, Any]]:
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
                      AND sa.source IN {AUTHOR_SOURCES_SQL}
                   ) AS pub_count
            FROM person_name_forms pnf
            WHERE pnf.person_id = :pid
            ORDER BY pnf.name_form
        """),
        {"pid": person_id},
    ).all()
    return [dict(r._mapping) for r in rows]


def person_admin(conn: Connection, person_id: int) -> dict[str, Any] | None:
    """Une personne par id, même projection que la liste admin (pour le drawer). None si absente."""
    row = conn.execute(
        text("""
            SELECT p.id, p.last_name, p.first_name,
                p.last_name_normalized, p.first_name_normalized,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh, p.rejected,
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id) AS signature_count,
                (SELECT COUNT(*) FROM authorships a
                 WHERE a.person_id = p.id AND a.in_perimeter = TRUE) AS in_perimeter_signature_count
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id = :id
        """),
        {"id": person_id},
    ).one_or_none()
    if row is None:
        return None
    persons_rows = [dict(row._mapping)]
    _attach_identifiers(conn, persons_rows, include_rejected=True)
    return persons_rows[0]
