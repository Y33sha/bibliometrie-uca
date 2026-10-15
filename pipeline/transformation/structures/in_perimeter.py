"""Recalcul ciblé du périmètre après une correction d'adresse par l'administration."""

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import AUTHORSHIP_PERIMETER_EVIDENCE_EXPR
from pipeline.transformation.publications.reconciliation.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)
from pipeline.transformation.structures.affiliations import (
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
        publication_ids = list(
            conn.execute(
                text(f"""
                    UPDATE authorships a
                    SET perimeter_evidence = {AUTHORSHIP_PERIMETER_EVIDENCE_EXPR}
                    FROM source_authorships changed
                    JOIN source_publications changed_sp ON changed_sp.id = changed.source_publication_id
                    WHERE changed.id = ANY(:ids)
                      AND a.publication_id = changed_sp.publication_id
                      AND a.person_id = changed.person_id
                    RETURNING a.publication_id
                """),
                {"ids": source_authorship_ids},
            ).scalars()
        )
        refresh_publications_perimeter_evidence(conn, publication_ids=sorted(set(publication_ids)))
