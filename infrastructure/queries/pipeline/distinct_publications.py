"""Query service : groupes de publications partageant une clé, pour la passe
`mark_distinct_publications`.

Appelé par `application/pipeline/publications/mark_distinct_publications.py`.
Implémente le port `DistinctPublicationsQueries`.
"""

from itertools import groupby

from sqlalchemy import Connection, text

from application.ports.pipeline.distinct_publications import (
    DistinctPublicationsQueries,
    PublicationForDistinct,
    SharedKeyGroup,
)


def find_publications_sharing_doi(conn: Connection) -> list[SharedKeyGroup]:
    """Groupes de publications partageant un même `lower(doi)` (≥ 2 publications).

    Chaque groupe porte les `doc_type` + `title_normalized` nécessaires à
    `detect_distinct_case`. Ordonné par DOI puis id pour un groupby déterministe.
    """
    rows = conn.execute(
        text("""
            WITH dups AS (
                SELECT lower(doi) AS doi_key
                FROM publications
                WHERE doi IS NOT NULL
                GROUP BY lower(doi)
                HAVING COUNT(*) > 1
            )
            SELECT lower(p.doi) AS doi_key, p.id,
                   p.doc_type::text AS doc_type, p.title_normalized
            FROM publications p
            JOIN dups ON dups.doi_key = lower(p.doi)
            ORDER BY doi_key, p.id
        """)
    ).all()
    return [
        SharedKeyGroup(
            key=key,
            publications=[
                PublicationForDistinct(
                    id=r.id, doc_type=r.doc_type, title_normalized=r.title_normalized
                )
                for r in grp
            ],
        )
        for key, grp in groupby(rows, key=lambda r: r.doi_key)
    ]


class PgDistinctPublicationsQueries(DistinctPublicationsQueries):
    """Adapter PostgreSQL pour `DistinctPublicationsQueries`."""

    def find_publications_sharing_doi(self, conn: Connection) -> list[SharedKeyGroup]:
        return find_publications_sharing_doi(conn)
