"""Les champs d'une revue saisis à la main

`journals.manual_fields` liste les champs que l'administration a saisis : le pipeline ne les écrit pas.

Revision ID: c7f3a0b5d469
Revises: b6e2f9a4c358
Create Date: 2026-10-11 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7f3a0b5d469"
down_revision: str | Sequence[str] | None = "b6e2f9a4c358"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE journals ADD COLUMN manual_fields text[] NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE journals DROP COLUMN manual_fields")
