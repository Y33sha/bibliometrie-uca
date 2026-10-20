"""SQL de construction de la table `authorships`, pour la phase `authorships`.

Regroupe les étapes SQL pures (INSERT, UPDATE FROM CTE) qui promeuvent les `source_authorships` en `authorships` consolidées.
"""

from sqlalchemy import Connection, text

from infrastructure.db.scalars import scalar_int
from infrastructure.sql_fragments import (
    insert_missing_authorships_sql,
    propagate_authorship_attributes_sql,
)
from pipeline.transformation.publications.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)


class AuthorshipsBuild:
    """Requêtes de construction des authorships."""

    def insert_missing_authorships(self, conn: Connection) -> int:
        return conn.execute(text(insert_missing_authorships_sql())).rowcount

    def prune_orphan_authorships(self, conn: Connection) -> int:
        return conn.execute(
            text("""
                DELETE FROM authorships a
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM source_authorships sa
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    WHERE sa.person_id = a.person_id
                      AND sd.publication_id = a.publication_id
                )
            """)
        ).rowcount

    def propagate_authorship_attributes(self, conn: Connection) -> int:
        return conn.execute(text(propagate_authorship_attributes_sql())).rowcount

    def refresh_authorship_structures(self, conn: Connection) -> None:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY authorship_structures"))

    def refresh_publication_structures(self, conn: Connection) -> None:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_structures"))

    def count_authorships_in_perimeter(self, conn: Connection) -> int:
        return scalar_int(
            conn.execute(text("SELECT COUNT(*) AS n FROM authorships WHERE in_perimeter = TRUE"))
        )

    def refresh_publications_perimeter_evidence(self, conn: Connection) -> int:
        return refresh_publications_perimeter_evidence(conn)
