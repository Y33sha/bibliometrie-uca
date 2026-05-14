"""Query service : SQL du script `create_publications`.

Appelé par `application/pipeline/create/create_publications.py`. Sélectionne
les `source_publications` in-perimeter orphelins (sans `publication_id`)
pour la création de l'entité consolidée `publications`.

L'attachement d'un `source_publications` à un `publications` est mutualisé
avec le script de fusion (voir `queries.merge.link_source_publication_to_publication`).
"""

from typing import Any

from sqlalchemy import Connection, text

from domain.persons.name_matching import parse_raw_author_name


def fetch_orphan_in_perimeter_source_publications(conn: Connection) -> list[dict[str, Any]]:
    """`source_publications` sans `publication_id` ayant au moins un
    `source_authorship` in_perimeter.

    Retourne les colonnes nécessaires pour la recherche/création de l'entité
    `publications` consolidée.
    """
    rows = conn.execute(
        text("""
            SELECT sd.id, sd.source::text AS source, sd.source_id, sd.doi, sd.title, sd.pub_year,
                   sd.doc_type::text AS doc_type, sd.journal_id, sd.oa_status::text AS oa_status,
                   sd.language, sd.container_title, sd.external_ids,
                   sd.is_retracted, sd.biblio, sd.abstract, sd.keywords, sd.topics
            FROM source_publications sd
            WHERE sd.publication_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM source_authorships sa
                  WHERE sa.source_publication_id = sd.id AND sa.in_perimeter = TRUE
              )
            ORDER BY sd.id
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def fetch_thesis_primary_author(conn: Connection, publication_id: int) -> tuple[str, str] | None:
    """Retourne `(last_name, first_name)` de l'auteur principal d'une publication thèse existante.

    Rôle `author`, tri par (source_publication_id, author_position), 1 ligne max. Parse via `domain.names.parse_raw_author_name`.
    """
    row = conn.execute(
        text("""
            SELECT sas.raw_author_name
            FROM source_authorships sas
            JOIN source_publications sd ON sd.id = sas.source_publication_id
            WHERE sd.publication_id = :pid
              AND 'author' = ANY(sas.roles)
            ORDER BY sd.id, sas.author_position
            LIMIT 1
        """),
        {"pid": publication_id},
    ).one_or_none()
    if row is None or not row.raw_author_name:
        return None
    last, first = parse_raw_author_name(row.raw_author_name)
    return (last, first) if last else None


def fetch_thesis_primary_author_from_source_publication(
    conn: Connection, source_publication_id: int
) -> tuple[str, str] | None:
    """Retourne `(last_name, first_name)` de l'auteur principal d'un `source_publication` courant (avant rattachement canonique).

    Rôle `author`, tri par `author_position`, 1 ligne max. Parse via `domain.names.parse_raw_author_name`.
    """
    row = conn.execute(
        text("""
            SELECT raw_author_name
            FROM source_authorships
            WHERE source_publication_id = :spid
              AND 'author' = ANY(roles)
            ORDER BY author_position
            LIMIT 1
        """),
        {"spid": source_publication_id},
    ).one_or_none()
    if row is None or not row.raw_author_name:
        return None
    last, first = parse_raw_author_name(row.raw_author_name)
    return (last, first) if last else None


class PgPublicationsCreateQueries:
    """Adapter PostgreSQL pour `application.ports.publications_create.PublicationsCreateQueries`.

    Délègue `link_source_publication_to_publication` à
    `infrastructure.db.queries.merge` (même SQL).
    """

    def fetch_orphan_in_perimeter_source_publications(
        self, conn: Connection
    ) -> list[dict[str, Any]]:
        return fetch_orphan_in_perimeter_source_publications(conn)

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None:
        from infrastructure.db.queries.merge import link_source_publication_to_publication

        link_source_publication_to_publication(conn, source_publication_id, publication_id)

    def fetch_thesis_primary_author(
        self, conn: Connection, publication_id: int
    ) -> tuple[str, str] | None:
        return fetch_thesis_primary_author(conn, publication_id)

    def fetch_thesis_primary_author_from_source_publication(
        self, conn: Connection, source_publication_id: int
    ) -> tuple[str, str] | None:
        return fetch_thesis_primary_author_from_source_publication(conn, source_publication_id)
