"""Query service : SQL de la phase `metadata_correction`.

Appelé par `application/pipeline/metadata_correction/`. Implémente le port
`application.ports.pipeline.metadata_correction.MetadataCorrectionQueries`.
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.metadata_correction import (
    CorrectionUpdate,
    DoiClusterRow,
    DoiCorrectionUpdate,
    MetadataCorrectionQueries,
    SourcePublicationForCorrection,
)

# Projection partagée : SP + champs joints `journals` (règles journal-dépendantes)
# + `raw_metadata` (reconstruction du brut). Le `WHERE` est ajouté par chaque variante.
_SELECT = """
    SELECT sp.id, sp.source::text AS source, sp.source_id,
           sp.title, sp.pub_year, sp.doc_type, sp.doi,
           sp.journal_id, sp.oa_status, sp.container_title, sp.language,
           sp.urls,
           j.journal_type::text AS journal_type, j.oa_model, j.apc_amount,
           sp.raw_metadata
    FROM source_publications sp
    LEFT JOIN journals j ON j.id = sp.journal_id
"""


def fetch_for_unary_correction(conn: Connection) -> list[SourcePublicationForCorrection]:
    """Toutes les `source_publications`, LEFT JOIN `journals` pour les champs des règles
    journal-dépendantes (`journal_type`, `oa_model`, `apc_amount`), `raw_metadata` inclus
    pour la reconstruction du brut."""
    rows = conn.execute(text(_SELECT)).all()
    return [SourcePublicationForCorrection(*row) for row in rows]


def fetch_for_unary_correction_by_journal(
    conn: Connection, journal_id: int
) -> list[SourcePublicationForCorrection]:
    """Les `source_publications` d'un journal (`journal_id = :jid`) — recompute ciblé."""
    rows = conn.execute(text(_SELECT + " WHERE sp.journal_id = :jid"), {"jid": journal_id}).all()
    return [SourcePublicationForCorrection(*row) for row in rows]


def fetch_doi_cluster_candidates(conn: Connection) -> list[DoiClusterRow]:
    """SP `book`/`book_chapter` ayant un DOI (brut reconstruit, en minuscules) pour la
    correction relationnelle group-by-DOI."""
    rows = conn.execute(
        text("""
            SELECT sp.id, sp.doc_type, sp.doi, sp.raw_metadata,
                   lower(COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi)) AS raw_doi
            FROM source_publications sp
            WHERE sp.doc_type IN ('book', 'book_chapter')
              AND COALESCE(sp.raw_metadata->'doi'->>'raw', sp.doi) IS NOT NULL
        """)
    ).all()
    return [DoiClusterRow(*row) for row in rows]


def persist_doi_corrections(conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
    """UPDATE en lot de la colonne `doi` + `raw_metadata`, bump `updated_at`."""
    if not updates:
        return 0
    stmt = text("""
        UPDATE source_publications
        SET doi = :doi,
            raw_metadata = :raw_metadata,
            updated_at = clock_timestamp()
        WHERE id = :id
    """).bindparams(bindparam("raw_metadata", type_=JSONB))
    conn.execute(stmt, [u._asdict() for u in updates])
    return len(updates)


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

    def fetch_for_unary_correction_by_journal(
        self, conn: Connection, journal_id: int
    ) -> list[SourcePublicationForCorrection]:
        return fetch_for_unary_correction_by_journal(conn, journal_id)

    def persist_corrections(self, conn: Connection, updates: list[CorrectionUpdate]) -> int:
        return persist_corrections(conn, updates)

    def fetch_doi_cluster_candidates(self, conn: Connection) -> list[DoiClusterRow]:
        return fetch_doi_cluster_candidates(conn)

    def persist_doi_corrections(self, conn: Connection, updates: list[DoiCorrectionUpdate]) -> int:
        return persist_doi_corrections(conn, updates)
