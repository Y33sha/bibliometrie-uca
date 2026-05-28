"""Query services admin sync pour les personnes : orphan authorships,
name-form authorships."""

from typing import Any

from sqlalchemy import Connection, text

from domain.persons.name_matching import parse_raw_author_name
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES_SQL
from domain.sources import AUTHOR_SOURCES_SQL

# ── Orphan authorships ───────────────────────────────────────────

# Filtre commun : in_perimeter, sans person_id, sources principales,
# hors doc_types out-of-scope
_ORPHAN_BASE = f"""
    sa.person_id IS NULL AND sa.in_perimeter = TRUE
    AND sa.source IN {AUTHOR_SOURCES_SQL}
    AND p.doc_type NOT IN {OUT_OF_SCOPE_DOC_TYPES_SQL}
    AND 'author' = ANY(sa.roles)
"""


def orphan_authorships_count(conn: Connection) -> dict[str, Any]:
    """Nombre d'authorships UCA sans person_id."""
    row = conn.execute(
        text(f"""
            SELECT COUNT(*) AS total
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
        """)
    ).one()
    return {"total": row.total}


def list_orphan_authorships(
    conn: Connection, *, search: str, page: int, per_page: int
) -> dict[str, Any]:
    """Liste paginée des authorships orphelines avec publication."""
    offset = (page - 1) * per_page
    search_cond = ""
    binds: dict[str, Any] = {}
    if search.strip():
        binds["search_pat"] = f"%{search.strip()}%"
        search_cond = "AND unaccent(lower(sa.raw_author_name)) LIKE unaccent(lower(:search_pat))"

    count_row = conn.execute(
        text(f"""
            SELECT COUNT(*) AS total FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
              {search_cond}
        """),
        binds,
    ).one()
    total = count_row.total

    rows = conn.execute(
        text(f"""
            SELECT sa.source, sa.id AS authorship_id,
                   sa.raw_author_name AS full_name,
                   sd.publication_id,
                   p.title AS pub_title, p.pub_year
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
              {search_cond}
            ORDER BY sa.raw_author_name, p.pub_year DESC
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {**binds, "pg_limit": per_page, "pg_offset": offset},
    ).all()
    # Décompose `raw_author_name` en last_name/first_name côté domain,
    # pour éviter de dupliquer la règle de parsing dans le frontend
    # (cf. domain/names.py::parse_raw_author_name).
    authorships: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row._mapping)
        last_name, first_name = parse_raw_author_name(data["full_name"])
        data["last_name"] = last_name
        data["first_name"] = first_name
        authorships.append(data)

    return {
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page or 1,
        "authorships": authorships,
    }


def person_exists(conn: Connection, person_id: int) -> bool:
    """Vérifie qu'une personne existe."""
    row = conn.execute(
        text("SELECT id FROM persons WHERE id = :id"),
        {"id": person_id},
    ).one_or_none()
    return row is not None


# ── Name-form authorships ────────────────────────────────────────


def name_form_authorships(conn: Connection, person_id: int, name_form: str) -> dict[str, Any]:
    """Authorships sources liées à une personne pour une forme de nom donnée
    + autres personnes partageant cette forme."""
    auth_rows = conn.execute(
        text(f"""
            SELECT sa.source, sa.id AS authorship_id,
                   sd.publication_id AS pub_id, sd.title, sd.pub_year, sd.doi
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.person_id = :pid AND sa.author_name_normalized = :nf
              AND sa.source IN {AUTHOR_SOURCES_SQL}
            ORDER BY sd.pub_year DESC, sd.title
        """),
        {"pid": person_id, "nf": name_form},
    ).all()
    authorships = [dict(r._mapping) for r in auth_rows]

    other_rows = conn.execute(
        text("""
            SELECT p.id, p.first_name, p.last_name,
                   pr.department_name,
                   EXISTS(SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id) AS has_rh
            FROM person_name_forms pnf
            JOIN persons p ON p.id = pnf.person_id
            LEFT JOIN persons_rh pr ON pr.person_id = p.id
            WHERE pnf.name_form = :nf
              AND pnf.person_id <> :pid
              AND p.rejected = FALSE
            ORDER BY p.last_name, p.first_name
        """),
        {"nf": name_form, "pid": person_id},
    ).all()
    other_persons = [dict(r._mapping) for r in other_rows]
    return {"authorships": authorships, "other_persons": other_persons}


def name_form_remaining_authorships(conn: Connection, person_id: int, name_form: str) -> int:
    """Compte les authorships qui restent liées à une personne pour un name_form."""
    row = conn.execute(
        text(f"""
            SELECT COUNT(*) AS total FROM source_authorships sa
            WHERE sa.person_id = :pid AND sa.author_name_normalized = :nf
              AND sa.source IN {AUTHOR_SOURCES_SQL}
        """),
        {"pid": person_id, "nf": name_form},
    ).one()
    return int(row.total)
