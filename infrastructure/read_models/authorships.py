"""Query service : lectures des signatures servies par les routes `/api/authorships/*`."""

from sqlalchemy import Connection, text

from application.ports.read_models.authorships_queries import (
    AuthorshipsQueries,
    OrphanAuthorshipOut,
    OrphanAuthorshipsResponse,
    OrphanCountResponse,
)
from application.ports.read_models.publications_queries import PubLabItem
from domain.persons.name_matching import parse_raw_author_name
from domain.sources.registry import AUTHOR_SOURCES
from domain.structures.structure import StructureType
from infrastructure.db.sql_fragments import in_clause

# Une signature est orpheline quand aucune personne ne la porte, dans le périmètre et sous un rôle d'auteur d'une source principale : c'est la matière que la file de rattachement présente.
_ORPHAN_BASE = f"""
    sa.person_id IS NULL AND sa.in_perimeter = TRUE
    AND sa.source IN {in_clause(AUTHOR_SOURCES)}
    AND 'author' = ANY(sa.roles)
"""


class PgAuthorshipsQueries(AuthorshipsQueries):
    """Adapter SA pour `application.ports.read_models.authorships_queries.AuthorshipsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def orphan_authorships_count(self) -> OrphanCountResponse:
        row = self._conn.execute(
            text(f"""
                SELECT COUNT(*) AS total
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                JOIN publications p ON p.id = sd.publication_id
                WHERE {_ORPHAN_BASE}
            """)
        ).one()
        return OrphanCountResponse(total=row.total)

    def list_orphan_authorships(
        self, *, search: str, page: int, per_page: int
    ) -> OrphanAuthorshipsResponse:
        offset = (page - 1) * per_page
        search_cond = ""
        binds: dict[str, object] = {}
        if search.strip():
            binds["search_pat"] = f"%{search.strip()}%"
            search_cond = (
                "AND unaccent(lower(sa.raw_author_name)) LIKE unaccent(lower(:search_pat))"
            )

        count_row = self._conn.execute(
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

        rows = self._conn.execute(
            text(f"""
                SELECT sa.source, sa.id AS source_authorship_id,
                       sa.raw_author_name AS full_name,
                       sd.publication_id,
                       p.title AS pub_title, p.pub_year,
                       COALESCE((
                           SELECT json_agg(lab ORDER BY lab.label)
                           FROM (
                               SELECT s.id, COALESCE(s.acronym, s.name) AS label
                               FROM source_authorship_structures sas
                               JOIN structures s ON s.id = sas.structure_id
                                AND s.structure_type = '{StructureType.LABO.value}'
                               WHERE sas.source_authorship_id = sa.id
                           ) lab
                       ), '[]') AS labs
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
        authorships: list[OrphanAuthorshipOut] = []
        for row in rows:
            last_name, first_name = parse_raw_author_name(row.full_name)
            authorships.append(
                OrphanAuthorshipOut(
                    source=row.source,
                    source_authorship_id=row.source_authorship_id,
                    full_name=row.full_name,
                    last_name=last_name,
                    first_name=first_name,
                    publication_id=row.publication_id,
                    pub_title=row.pub_title,
                    pub_year=row.pub_year,
                    labs=[PubLabItem(**lab) for lab in row.labs],
                )
            )

        return OrphanAuthorshipsResponse(
            total=total, page=page, per_page=per_page, authorships=authorships
        )


__all__ = ["PgAuthorshipsQueries"]
