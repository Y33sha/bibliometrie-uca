"""Suppression des pays suggérés des adresses

La page d'attribution des pays lit les pays trouvés par chaque moyen de détection (`address_country_candidates`).

Revision ID: c3a1f0d27b94
Revises: 82940fac13cc
Create Date: 2026-10-16 23:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3a1f0d27b94"
down_revision: str | Sequence[str] | None = "82940fac13cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE structures.addresses DROP COLUMN suggested_countries")


def downgrade() -> None:
    op.execute("ALTER TABLE structures.addresses ADD COLUMN suggested_countries char(2)[]")
