"""Titre de la notice Sudoc de chaque ISSN

Revision ID: b3e9f7a2c618
Revises: a8d2c5f1e374
Create Date: 2026-11-01 01:00:00.000000

`serial_issns.sudoc_title` garde le titre de la notice Sudoc de chaque ISSN. Le titre d'une revue en dérive, d'après son ISSN-L. Chaque ISSN repasse à la vérification Sudoc, qui remplit la colonne.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3e9f7a2c618"
down_revision: str | Sequence[str] | None = "a8d2c5f1e374"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE publishing.serial_issns ADD COLUMN sudoc_title text;
        COMMENT ON COLUMN publishing.serial_issns.sudoc_title IS
        'Titre de la notice Sudoc de l''ISSN. NULL : sans notice, ou ISSN jamais vérifié.';
        UPDATE publishing.serial_issns SET sudoc_checked_at = NULL
        WHERE sudoc_checked_at IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE publishing.serial_issns DROP COLUMN sudoc_title")
