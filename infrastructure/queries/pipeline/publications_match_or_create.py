"""Query service : SQL de la phase `match_or_create_publications`.

Appelé par `application/pipeline/publications/match_or_create_publications.py` :

1. **SELECT orphelins** (`fetch_orphan_source_publications`) : tous les orphelins (`publication_id IS NULL`) avec leur périmètre réel, traités un par un via la cascade Python `decide_publication_match` (match quel que soit le périmètre, création gatée `in_perimeter`).
2. **SELECT publications stale** (`fetch_stale_publication_ids`) pour ré-agrégation des méta canoniques.

L'attachement d'un `source_publications` à un `publications` (`link_source_publication_to_publication`) est un simple `UPDATE source_publications SET publication_id`.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.publications_match_or_create import (
    PublicationsMatchOrCreateQueries,
    SourcePublicationRow,
)


def fetch_orphan_source_publications(conn: Connection) -> list[SourcePublicationRow]:
    """Tous les orphelins (`publication_id IS NULL`), périmètre réel calculé en ligne.

    `in_perimeter` = TRUE ssi ≥1 `source_authorship` rattaché est in_perimeter ; il gate la création (`allow_create`), pas le rattachement. Traités un par un par la cascade `decide_publication_match`.
    """
    rows = conn.execute(
        text("""
            SELECT sd.id, sd.source::text AS source, sd.source_id, sd.doi, sd.title, sd.pub_year,
                   sd.doc_type::text AS doc_type, sd.journal_id, sd.oa_status::text AS oa_status,
                   sd.language, sd.container_title, sd.external_ids, sd.urls,
                   EXISTS (
                       SELECT 1 FROM source_authorships sa
                       WHERE sa.source_publication_id = sd.id AND sa.in_perimeter = TRUE
                   ) AS in_perimeter
            FROM source_publications sd
            WHERE sd.publication_id IS NULL
            ORDER BY sd.id
        """)
    ).all()
    return [SourcePublicationRow(**r._mapping) for r in rows]


def fetch_stale_publication_ids(conn: Connection) -> list[int]:
    """Publications dont au moins un `source_publication` a été modifié depuis le dernier refresh canonique.

    Comparaison `source_publications.updated_at > publications.updated_at` : indique qu'une normalisation récente a apporté des changements de méta (oa_status, abstract, biblio, …) que le canonique ne reflète pas encore. `refresh_from_sources` recalcule les méta agrégées et met `publications.updated_at = now()` au passage, ce qui ferme la fenêtre.
    """
    rows = conn.execute(
        text("""
            SELECT p.id
            FROM publications p
            WHERE EXISTS (
                SELECT 1 FROM source_publications sp
                WHERE sp.publication_id = p.id
                  AND sp.updated_at > p.updated_at
            )
            ORDER BY p.id
        """)
    ).all()
    return [row.id for row in rows]


class PgPublicationsMatchOrCreateQueries(PublicationsMatchOrCreateQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.publications_match_or_create.PublicationsMatchOrCreateQueries`."""

    def fetch_orphan_source_publications(self, conn: Connection) -> list[SourcePublicationRow]:
        return fetch_orphan_source_publications(conn)

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None:
        conn.execute(
            text("UPDATE source_publications SET publication_id = :pid WHERE id = :sd_id"),
            {"pid": publication_id, "sd_id": source_publication_id},
        )

    def fetch_stale_publication_ids(self, conn: Connection) -> list[int]:
        return fetch_stale_publication_ids(conn)
