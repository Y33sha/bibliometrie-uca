"""Signatures collectives

`source_authorships.collective` vaut vrai pour une signature collective (collaboration, consortium, groupe d'étude…). La normalisation la pose d'après le signal de la source, ou d'après le nom.

Revision ID: 8b3f1c2e9d54
Revises: 5d2e8b61c4a7
Create Date: 2026-10-17 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8b3f1c2e9d54"
down_revision: str | Sequence[str] | None = "5d2e8b61c4a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sources.source_authorships ADD COLUMN collective boolean NOT NULL DEFAULT false;
        COMMENT ON COLUMN sources.source_authorships.collective IS
            'Signature collective (collaboration, consortium, groupe d''étude…), posée par la normalisation d''après le signal de la source ou d''après le nom.';
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE sources.source_authorships DROP COLUMN collective")
