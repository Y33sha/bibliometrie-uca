"""Query service : SQL de la phase `metadata_correction`.

Appelé par `application/pipeline/metadata_correction/`. Implémente le port
`application.ports.pipeline.metadata_correction.MetadataCorrectionQueries`.
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.metadata_correction import (
    CorrectionUpdate,
    MetadataCorrectionQueries,
    SourcePublicationForCorrection,
)


def fetch_for_unary_correction(conn: Connection) -> list[SourcePublicationForCorrection]:
    """Toutes les `source_publications`, LEFT JOIN `journals` pour les champs des règles
    journal-dépendantes (`journal_type`, `oa_model`, `apc_amount`), `raw_metadata` inclus
    pour la reconstruction du brut."""
    rows = conn.execute(
        text("""
            SELECT sp.id, sp.source::text AS source, sp.source_id,
                   sp.title, sp.pub_year, sp.doc_type, sp.doi,
                   sp.journal_id, sp.oa_status, sp.container_title, sp.language,
                   sp.urls,
                   j.journal_type::text AS journal_type, j.oa_model, j.apc_amount,
                   sp.raw_metadata
            FROM source_publications sp
            LEFT JOIN journals j ON j.id = sp.journal_id
        """)
    ).all()
    return [SourcePublicationForCorrection(*row) for row in rows]


def persist_corrections(conn: Connection, updates: list[CorrectionUpdate]) -> int:
    """UPDATE en lot des colonnes effectives + `raw_metadata`, bump `updated_at`."""
    if not updates:
        return 0
    stmt = text("""
        UPDATE source_publications
        SET doc_type = :doc_type,
            journal_id = :journal_id,
            oa_status = :oa_status,
            raw_metadata = :raw_metadata,
            updated_at = clock_timestamp()
        WHERE id = :id
    """).bindparams(bindparam("raw_metadata", type_=JSONB))
    conn.execute(stmt, [u._asdict() for u in updates])
    return len(updates)


class PgMetadataCorrectionQueries(MetadataCorrectionQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.metadata_correction.MetadataCorrectionQueries`."""

    def fetch_for_unary_correction(self, conn: Connection) -> list[SourcePublicationForCorrection]:
        return fetch_for_unary_correction(conn)

    def persist_corrections(self, conn: Connection, updates: list[CorrectionUpdate]) -> int:
        return persist_corrections(conn, updates)
