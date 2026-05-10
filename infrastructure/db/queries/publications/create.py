"""Query service : SQL du script `create_publications`.

Appelé par `application/pipeline/create/create_publications.py`. Sélectionne
les `source_publications` in-perimeter orphelins (sans `publication_id`)
pour la création de l'entité consolidée `publications`.

L'attachement d'un `source_publications` à un `publications` est mutualisé
avec le script de fusion (voir `queries.merge.link_source_publication_to_publication`).
"""

from typing import Any

from sqlalchemy import Connection, text


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
