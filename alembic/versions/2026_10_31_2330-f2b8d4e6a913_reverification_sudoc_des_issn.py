"""Revérification Sudoc de tous les ISSN

Revision ID: f2b8d4e6a913
Revises: e7c3a9d1f482
Create Date: 2026-10-31 23:30:00.000000

Chaque ISSN repasse à la vérification Sudoc. Elle remplit `issn_links` et réécrit le titre Sudoc de la revue de chaque ISSN-L.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f2b8d4e6a913"
down_revision: str | Sequence[str] | None = "e7c3a9d1f482"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE publishing.serial_issns SET sudoc_checked_at = NULL"
        " WHERE sudoc_checked_at IS NOT NULL"
    )


def downgrade() -> None:
    """Sans effet : la vérification Sudoc suivante rétablit les dates."""
