"""Retrait de source_records.topics

Revision ID: 2ac26ec26f63
Revises: e56b7ba228e7
Create Date: 2026-11-01 09:00:00.000000

Les sujets d'un enregistrement source sont dans `sources.source_record_subjects`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "2ac26ec26f63"
down_revision: str | Sequence[str] | None = "e56b7ba228e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sources.source_records DROP COLUMN topics")


def downgrade() -> None:
    op.execute("ALTER TABLE sources.source_records ADD COLUMN topics jsonb")
