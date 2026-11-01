"""Retrait de publications_detail.topics

Revision ID: 19301d8c9878
Revises: 90aaceaeda15
Create Date: 2026-11-01 06:00:00.000000

La colonne copie les `topics` des enregistrements sources de chaque publication. Aucune lecture ne l'utilise. Les sujets viennent de `source_records.topics`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "19301d8c9878"
down_revision: str | Sequence[str] | None = "90aaceaeda15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE publications.publications_detail DROP COLUMN topics")


def downgrade() -> None:
    op.execute("ALTER TABLE publications.publications_detail ADD COLUMN topics jsonb")
