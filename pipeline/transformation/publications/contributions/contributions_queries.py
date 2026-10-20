"""SQL de construction de la table `contributions`, pour la phase `contributions`.

Regroupe les étapes SQL pures (INSERT, UPDATE FROM CTE) qui promeuvent les `source_contributions` en `contributions` consolidées.
"""

from sqlalchemy import Connection, text

from infrastructure.db.scalars import scalar_int
from infrastructure.sql_fragments import (
    insert_missing_contributions_sql,
    propagate_contribution_attributes_sql,
)
from pipeline.transformation.publications.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)


class ContributionsBuild:
    """Requêtes de construction des contributions."""

    def insert_missing_contributions(self, conn: Connection) -> int:
        return conn.execute(text(insert_missing_contributions_sql())).rowcount

    def prune_orphan_contributions(self, conn: Connection) -> int:
        return conn.execute(
            text("""
                DELETE FROM contributions a
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM source_contributions sc
                    JOIN source_records sr ON sr.id = sc.source_record_id
                    WHERE sc.person_id = a.person_id
                      AND sr.publication_id = a.publication_id
                )
            """)
        ).rowcount

    def propagate_contribution_attributes(self, conn: Connection) -> int:
        return conn.execute(text(propagate_contribution_attributes_sql())).rowcount

    def refresh_contribution_structures(self, conn: Connection) -> None:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY contribution_structures"))

    def refresh_publication_structures(self, conn: Connection) -> None:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_structures"))

    def count_contributions_in_perimeter(self, conn: Connection) -> int:
        return scalar_int(
            conn.execute(text("SELECT COUNT(*) AS n FROM contributions WHERE in_perimeter = TRUE"))
        )

    def refresh_publications_perimeter_evidence(self, conn: Connection) -> int:
        return refresh_publications_perimeter_evidence(conn)
