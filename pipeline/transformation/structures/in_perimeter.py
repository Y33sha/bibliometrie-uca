"""Recalcul ciblé du périmètre après une correction d'adresse par l'administration."""

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import SIGNATURES_SCOPE, propagate_authorship_attributes_sql
from pipeline.transformation.publications.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)
from pipeline.transformation.structures.perimeter_evidence import (
    refresh_source_authorship_structures,
    sync_perimeter_evidence,
)


class InPerimeterRecompute:
    """Recalcul ciblé du périmètre (port `AffiliationsQueries`, injecté par l'API)."""

    def recompute_perimeter(
        self,
        conn: Connection,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        """Rafraîchit la matview `source_authorship_structures`, puis recalcule les indices des signatures données, de leurs authorships et de leurs publications, par les mêmes requêtes que le pipeline."""
        refresh_source_authorship_structures(conn)
        sync_perimeter_evidence(
            conn, perimeter_ids=perimeter_structure_ids, signature_ids=source_authorship_ids
        )
        conn.execute(
            text(propagate_authorship_attributes_sql(scope=SIGNATURES_SCOPE)),
            {"signature_ids": source_authorship_ids},
        )
        publication_ids = conn.execute(
            text("""
                SELECT DISTINCT sp.publication_id
                FROM source_authorships sa
                JOIN source_publications sp ON sp.id = sa.source_publication_id
                WHERE sa.id = ANY(:ids) AND sp.publication_id IS NOT NULL
                ORDER BY 1
            """),
            {"ids": source_authorship_ids},
        ).scalars()
        refresh_publications_perimeter_evidence(conn, publication_ids=list(publication_ids))
