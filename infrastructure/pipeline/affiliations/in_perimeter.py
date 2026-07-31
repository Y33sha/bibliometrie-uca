"""Query service : résolution des affiliations sur `source_authorships`, phase `affiliations`.

Appelé par `application/pipeline/affiliations/populate_affiliations.py` : rafraîchit la matview `source_authorship_structures`, puis pose `in_perimeter` depuis celle-ci.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.affiliations.in_perimeter import (
    AffiliationsQueries,
    InPerimeterSyncCounts,
)
from infrastructure.db.sql_fragments import AUTHORSHIP_IN_PERIMETER_EXPR

# Ensembles d'ids des deux UPDATE de `sync_in_perimeter` : `should` (authorships du périmètre restreint, via la matview) et `currently` (à TRUE, via l'index partiel). Delta par EXCEPT ; un run stable produit un delta vide.
_DELTA_CTE = """
    WITH should AS (
        SELECT DISTINCT source_authorship_id AS id
        FROM source_authorship_structures
        WHERE structure_id = ANY(:perimeter_ids)
    ),
    currently AS (
        SELECT id FROM source_authorships WHERE in_perimeter
    )
"""


class PgAffiliationsQueries(AffiliationsQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.affiliations.in_perimeter.AffiliationsQueries`."""

    def sync_in_perimeter(
        self, conn: Connection, *, perimeter_ids: list[int]
    ) -> InPerimeterSyncCounts:
        params = {"perimeter_ids": perimeter_ids}
        added = conn.execute(
            text(
                _DELTA_CTE
                + """
                UPDATE source_authorships
                SET in_perimeter = TRUE
                WHERE id IN (SELECT id FROM should EXCEPT SELECT id FROM currently)
            """
            ),
            params,
        ).rowcount
        removed = conn.execute(
            text(
                _DELTA_CTE
                + """
                UPDATE source_authorships
                SET in_perimeter = FALSE
                WHERE id IN (SELECT id FROM currently EXCEPT SELECT id FROM should)
            """
            ),
            params,
        ).rowcount
        return InPerimeterSyncCounts(added=added, removed=removed)

    def refresh_source_authorship_structures(self, conn: Connection) -> None:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY source_authorship_structures"))

    def recompute_in_perimeter_on_source_authorships(
        self,
        conn: Connection,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        conn.execute(
            text("""
                UPDATE source_authorships sa
                SET in_perimeter = EXISTS (
                    SELECT 1
                    FROM source_authorship_addresses saa
                    JOIN address_structures ast ON ast.address_id = saa.address_id
                    WHERE saa.source_authorship_id = sa.id
                      AND ast.structure_id = ANY(:struct_ids)
                      AND ast.is_confirmed IS DISTINCT FROM FALSE
                )
                WHERE sa.id = ANY(:source_authorship_ids)
            """),
            {"source_authorship_ids": source_authorship_ids, "struct_ids": perimeter_structure_ids},
        )

    def propagate_in_perimeter_to_authorships(
        self, conn: Connection, source_authorship_ids: list[int]
    ) -> None:
        # Propage `in_perimeter` vers les `authorships` consolidées ; les structures dérivées (matview `authorship_structures`) restent au pipeline.
        conn.execute(
            text("""
                CREATE TEMP TABLE _affected_authorships AS
                SELECT DISTINCT a.id AS authorship_id
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                JOIN authorships a ON a.publication_id = sd.publication_id
                                  AND a.person_id = sa.person_id
                WHERE sa.id = ANY(:ids)
                  AND sd.publication_id IS NOT NULL
                  AND sa.person_id IS NOT NULL
            """),
            {"ids": source_authorship_ids},
        )
        conn.execute(
            text(f"""
                UPDATE authorships a
                SET in_perimeter = {AUTHORSHIP_IN_PERIMETER_EXPR}
                FROM _affected_authorships af
                WHERE a.id = af.authorship_id
            """)
        )
        conn.execute(text("DROP TABLE _affected_authorships"))
