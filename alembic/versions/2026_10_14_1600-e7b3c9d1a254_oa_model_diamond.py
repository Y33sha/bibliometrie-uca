"""Ajoute la valeur 'diamond' à l'enum oa_model

Une revue en open access sans frais de publication, absente du DOAJ, se marque diamant à la main.

Revision ID: e7b3c9d1a254
Revises: c4e8a2f6b913
Create Date: 2026-10-14 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7b3c9d1a254"
down_revision: str | Sequence[str] | None = "c4e8a2f6b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE public.oa_model ADD VALUE IF NOT EXISTS 'diamond' AFTER 'full_oa'")


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade recrée le type sans
    # 'diamond' : les revues marquées diamant reviennent à 'full_oa'.
    op.execute("UPDATE publishing.journals SET oa_model = 'full_oa' WHERE oa_model = 'diamond'")
    op.execute("ALTER TYPE public.oa_model RENAME TO oa_model_old")
    op.execute("CREATE TYPE public.oa_model AS ENUM ('subscription', 'full_oa', 'repository')")
    op.execute(
        "ALTER TABLE publishing.journals "
        "ALTER COLUMN oa_model TYPE public.oa_model USING oa_model::text::public.oa_model"
    )
    op.execute("DROP TYPE public.oa_model_old")
