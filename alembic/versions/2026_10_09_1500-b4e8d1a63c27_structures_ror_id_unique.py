"""Unicité de structures.ror_id

Un identifiant ROR désigne une seule structure.

Revision ID: b4e8d1a63c27
Revises: a7c2e5f91b3d
Create Date: 2026-10-09 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b4e8d1a63c27"
down_revision: str | Sequence[str] | None = "a7c2e5f91b3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.structures ADD CONSTRAINT structures_ror_id_key UNIQUE (ror_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE public.structures DROP CONSTRAINT structures_ror_id_key")
