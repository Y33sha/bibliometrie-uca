"""Query service : lectures des signatures servies par les routes `/api/authorships/*`."""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.authorships_queries import (
    AuthorshipsQueries,
    OrphanAuthorshipsResponse,
    OrphanCountResponse,
)
from domain.persons.name_matching import parse_raw_author_name
from infrastructure.queries.sources_sql import AUTHOR_SOURCES_SQL

# Une signature est orpheline quand aucune personne ne la porte, dans le périmètre et sous un rôle d'auteur d'une source principale : c'est la matière que la file de rattachement présente.
_ORPHAN_BASE = f"""
    sa.person_id IS NULL AND sa.in_perimeter = TRUE
    AND sa.source IN {AUTHOR_SOURCES_SQL}
    AND 'author' = ANY(sa.roles)
"""


def orphan_authorships_count(conn: Connection) -> dict[str, Any]:
    """Nombre de signatures du périmètre qu'aucune personne ne porte."""
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
    """Liste paginée des signatures orphelines, avec la publication qu'elles signent."""
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
            SELECT sa.source, sa.id AS source_authorship_id,
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
    # Décompose `raw_author_name` en last_name/first_name via `parse_raw_author_name`, la règle de parsing unique du domaine.
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
        "per_page": per_page,
        "authorships": authorships,
    }


class PgAuthorshipsQueries(AuthorshipsQueries):
    """Adapter SA pour `application.ports.api.authorships_queries.AuthorshipsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def orphan_authorships_count(self) -> OrphanCountResponse:
        return OrphanCountResponse.model_validate(orphan_authorships_count(self._conn))

    def list_orphan_authorships(
        self, *, search: str, page: int, per_page: int
    ) -> OrphanAuthorshipsResponse:
        return OrphanAuthorshipsResponse.model_validate(
            list_orphan_authorships(self._conn, search=search, page=page, per_page=per_page)
        )


__all__ = ["PgAuthorshipsQueries"]
