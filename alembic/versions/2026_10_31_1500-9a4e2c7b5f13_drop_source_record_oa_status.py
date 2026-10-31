"""Suppression du statut open access des enregistrements sources

Le statut open access d'une publication se déduit de ses copies, de ses embargos, de sa revue et du verdict d'Unpaywall. La colonne `oa_status` des enregistrements sources et ses corrections sont supprimées.

Revision ID: 9a4e2c7b5f13
Revises: 5d2f8b3c9e61
Create Date: 2026-10-31 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9a4e2c7b5f13"
down_revision: str | Sequence[str] | None = "5d2f8b3c9e61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE sources.source_records SET corrections = corrections - 'oa_status'
        WHERE corrections ? 'oa_status'
    """)
    op.execute("ALTER TABLE sources.source_records DROP COLUMN oa_status")


def downgrade() -> None:
    op.execute("ALTER TABLE sources.source_records ADD COLUMN oa_status text")
