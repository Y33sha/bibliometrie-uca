"""Commentaire de `source_authorships.duplicate_of` : doublon d'auteur

Revision ID: 9a2c4f6b8d13
Revises: 7d3b5e9a1c42
Create Date: 2026-10-18 23:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9a2c4f6b8d13"
down_revision: str | Sequence[str] | None = "7d3b5e9a1c42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        COMMENT ON COLUMN sources.source_authorships.duplicate_of IS
            'Doublon d''auteur : signature qui répète, dans la liste d''auteurs de sa notice, la signature référencée. Écrite par la phase author_grouping.'
    """)


def downgrade() -> None:
    op.execute("""
        COMMENT ON COLUMN sources.source_authorships.duplicate_of IS
            'Signature dont celle-ci est la copie, dans une liste d''auteurs recopiée par la source. Écrite par la phase author_grouping.'
    """)
