"""DOI des formes secondaires rendus à leurs enregistrements sources

Revision ID: c7e2a9f4b1d8
Revises: c4e8a2f6b1d3
Create Date: 2026-10-29 13:00:00.000000

Le DOI d'une version, d'une variante ou d'une pièce de dataset a une cible dans `doi_targets`. Les enregistrements sources retrouvent leur DOI d'origine, actif, et sont marqués pour la réconciliation.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7e2a9f4b1d8"
down_revision: str | Sequence[str] | None = "c4e8a2f6b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULES = "('DATACITE_VERSION_TO_CONCEPT', 'DATACITE_VARIANT_TO_PRIMARY', 'DATACITE_PACKAGE_PIECE')"


def upgrade() -> None:
    op.execute(f"""
        WITH restored AS (
            UPDATE sources.source_records
            SET doi = corrections -> 'doi' ->> 'raw', corrections = corrections - 'doi'
            WHERE corrections -> 'doi' ->> 'corrected_by' IN {_RULES}
            RETURNING id
        ), reactivated AS (
            UPDATE sources.source_record_identifiers
            SET removed_by = NULL
            WHERE removed_by IN {_RULES}
            RETURNING source_record_id AS id
        )
        INSERT INTO queues.source_record_keys_queue (id)
        SELECT id FROM restored UNION SELECT id FROM reactivated
        ON CONFLICT (id) DO UPDATE SET seq = DEFAULT;
    """)


def downgrade() -> None:
    """Les DOI retirés se recalculent seulement avec le code qui les retirait."""
