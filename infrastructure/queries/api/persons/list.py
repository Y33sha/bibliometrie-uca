"""Annuaire public + autocomplete + liste admin des personnes (sync)."""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.persons_queries import DirectoryFilters, ListFilters
from domain.persons.identifiers import PUBLIC_PERSON_IDENTIFIER_TYPES
from infrastructure.queries.filters import (
    WhereClause,
    assemble_where,
    person_has_identifier_clause,
    person_has_pending_identifiers_clause,
    person_has_pending_name_forms_clause,
    person_has_rh_clause,
    person_in_lab_clause,
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
    if filters.departments:
        clauses.append(
            WhereClause(
                "prh.department_name = ANY(:flt_departments)",
                {"flt_departments": filters.departments},
            )
        )
    if filters.roles:
        clauses.append(
            WhereClause("prh.role_title = ANY(:flt_roles)", {"flt_roles": filters.roles})
        )
    clauses.append(person_has_identifier_clause("orcid", filters.has_orcid))
    clauses.append(person_has_identifier_clause("idhal", filters.has_idhal))
    clauses.append(person_has_identifier_clause("idref", filters.has_idref))
    clauses.append(person_has_rh_clause(filters.has_rh))
    clauses.append(person_in_lab_clause(filters.lab_id))

    where_sql, binds = assemble_where(clauses)
    order = persons_sort_clause(sort)

    # En contexte labo, `pub_count` est scopé aux publications du labo (cohérent
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
                ) AS pub_count,
                (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status IN ('confirmed', 'authenticated'))))
                 FROM person_identifiers pi
                 WHERE pi.person_id = p.id AND pi.id_type = 'orcid' AND pi.status != 'rejected'
                ) AS orcids,
                (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status IN ('confirmed', 'authenticated'))))
                 FROM person_identifiers pi
                 WHERE pi.person_id = p.id AND pi.id_type = 'idhal' AND pi.status != 'rejected'
                ) AS idhals,
                (SELECT json_agg(json_build_object('value', pi.id_value, 'confirmed', (pi.status IN ('confirmed', 'authenticated'))))
                 FROM person_identifiers pi
                 WHERE pi.person_id = p.id AND pi.id_type = 'idref' AND pi.status != 'rejected'
                ) AS idrefs
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE {where_sql}
            ORDER BY {order}
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {**binds, "pg_limit": per_page, "pg_offset": offset},
    ).all()
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "persons": [dict(r._mapping) for r in rows],
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
    "name": "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC",
    "-name": "LOWER(p.last_name) DESC, LOWER(p.first_name) DESC",
    "pubs": "pub_count ASC, LOWER(p.last_name) ASC",
    "-pubs": "pub_count DESC, LOWER(p.last_name) ASC",
    "uca_pubs": "uca_pub_count ASC, LOWER(p.last_name) ASC",
    "-uca_pubs": "uca_pub_count DESC, LOWER(p.last_name) ASC",
}


def list_persons(
    conn: Connection, *, filters: ListFilters, page: int, per_page: int, sort: str
) -> dict[str, Any]:
    """Liste des personnes avec filtres (admin)."""
    offset = (page - 1) * per_page
    clauses: list[WhereClause | None] = []

    if filters.search:
        clauses.append(
            WhereClause(
                """(
                    unaccent(p.last_name) ILIKE unaccent(:search_pat)
                    OR unaccent(p.first_name) ILIKE unaccent(:search_pat)
                    OR prh.email ILIKE :search_pat
                )""",
                {"search_pat": f"%{filters.search}%"},
            )
        )
    if filters.department:
        clauses.append(
            WhereClause(
                "prh.department_name = :flt_department", {"flt_department": filters.department}
            )
        )
    if filters.role:
        clauses.append(WhereClause("prh.role_title = :flt_role", {"flt_role": filters.role}))
    clauses.append(person_has_identifier_clause("orcid", filters.has_orcid))
    clauses.append(person_has_identifier_clause("idhal", filters.has_idhal))
    clauses.append(person_has_identifier_clause("idref", filters.has_idref))
    clauses.append(person_has_rh_clause(filters.has_rh))
    clauses.append(person_has_pending_name_forms_clause(filters.has_pending_forms))
    clauses.append(person_has_pending_identifiers_clause(filters.has_pending_identifiers))

    where_sql, binds = assemble_where(clauses)
    order = _LIST_SORT_MAP.get(sort, _LIST_SORT_MAP["name"])

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
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id) AS pub_count,
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id AND a.in_perimeter = TRUE) AS uca_pub_count
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE {where_sql}
            ORDER BY {order}
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {**binds, "pg_limit": per_page, "pg_offset": offset},
    ).all()
    persons_rows = [dict(r._mapping) for r in rows]
    _attach_identifiers_and_name_forms(conn, persons_rows)

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "persons": persons_rows,
    }


def _attach_identifiers_and_name_forms(
    conn: Connection, persons_rows: list[dict[str, Any]]
) -> None:
    """Enrichit en place chaque ligne personne (liste admin) avec ses identifiants
    et ses formes de nom (statut, shared_count, pub_count)."""
    person_ids = [p["id"] for p in persons_rows]
    if not person_ids:
        return

    identifiers_map: dict[int, Any] = {}
    id_rows = conn.execute(
        text("""
            SELECT pi.person_id,
                   json_agg(json_build_object(
                       'id', pi.id, 'id_type', pi.id_type, 'id_value', pi.id_value,
                       'source', pi.source, 'status', pi.status
                   ) ORDER BY pi.id_type, pi.id_value) AS identifiers
            FROM person_identifiers pi
            WHERE pi.person_id = ANY(:ids)
              AND pi.id_type = ANY(:public_id_types)
            GROUP BY pi.person_id
        """),
        {"ids": person_ids, "public_id_types": list(PUBLIC_PERSON_IDENTIFIER_TYPES)},
    ).all()
    for r in id_rows:
        identifiers_map[r.person_id] = r.identifiers

    # Toutes les formes de la personne, y compris celles entièrement dérivées du nom
    # canonique (source 'persons' seule) : le drawer admin les affiche pour la curation.
    # `shared_count` / `ambiguous` : nombre de person_id portant ce name_form.
    name_forms_map: dict[int, Any] = {}
    nf_rows = conn.execute(
        text(f"""
            SELECT pnf.person_id,
                   json_agg(json_build_object(
                       'name_form', pnf.name_form,
                       'sources', pnf.sources,
                       'status', pnf.status::text,
                       'shared_count', (
                           SELECT COUNT(*)
                           FROM person_name_forms p2
                           WHERE p2.name_form = pnf.name_form
                       ),
                       'ambiguous', (
                           SELECT COUNT(*) > 1
                           FROM person_name_forms p2
                           WHERE p2.name_form = pnf.name_form
                       ),
                       'pub_count', (
                           SELECT COUNT(DISTINCT sd.publication_id)
                           FROM source_authorships sa
                           JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                           JOIN source_publications sd ON sd.id = sa.source_publication_id
                           WHERE sa.person_id = pnf.person_id
                             AND aik.author_name_normalized = pnf.name_form
                             AND sa.source IN {AUTHOR_SOURCES_SQL}
                       )
                   ) ORDER BY pnf.name_form) AS name_forms
            FROM person_name_forms pnf
            WHERE pnf.person_id = ANY(:ids)
            GROUP BY pnf.person_id
        """),
        {"ids": person_ids},
    ).all()
    for r in nf_rows:
        name_forms_map[r.person_id] = r.name_forms

    for p in persons_rows:
        p["identifiers"] = identifiers_map.get(p["id"])
        p["name_forms"] = name_forms_map.get(p["id"])


def person_admin(conn: Connection, person_id: int) -> dict[str, Any] | None:
    """Une personne par id, même projection que la liste admin (pour le drawer). None si absente."""
    row = conn.execute(
        text("""
            SELECT p.id, p.last_name, p.first_name,
                p.last_name_normalized, p.first_name_normalized,
                prh.role_title, prh.department_name, prh.start_date, prh.end_date,
                (prh.id IS NOT NULL) AS has_rh, p.rejected,
                (SELECT COUNT(*) FROM authorships a WHERE a.person_id = p.id) AS pub_count,
                (SELECT COUNT(*) FROM authorships a
                 WHERE a.person_id = p.id AND a.in_perimeter = TRUE) AS uca_pub_count
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id = :id
        """),
        {"id": person_id},
    ).one_or_none()
    if row is None:
        return None
    persons_rows = [dict(row._mapping)]
    _attach_identifiers_and_name_forms(conn, persons_rows)
    return persons_rows[0]
