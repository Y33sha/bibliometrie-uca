"""Index du premier hal_id d'`external_ids` supprimé

Revision ID: c4f9a2e7b1d3
Revises: b8e3c1d7a4f2
Create Date: 2026-10-28 21:00:00.000000

La réconciliation rapproche les enregistrements sources par `source_record_identifiers`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4f9a2e7b1d3"
down_revision: str | Sequence[str] | None = "b8e3c1d7a4f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX sources.idx_source_records_first_hal_id;")


def downgrade() -> None:
    op.execute("""
        CREATE INDEX idx_source_records_first_hal_id ON sources.source_records
        USING btree (((external_ids -> 'hal_id') ->> 0))
        WHERE ((external_ids -> 'hal_id') ->> 0) IS NOT NULL;
    """)
