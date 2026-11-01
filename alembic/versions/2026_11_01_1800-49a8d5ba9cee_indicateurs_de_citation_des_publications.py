"""Indicateurs de citation dans `publications.impact`

Revision ID: 49a8d5ba9cee
Revises: 662b5308f866
Create Date: 2026-11-01 18:00:00.000000

La colonne JSONB `impact` d'une publication reprend les indicateurs de citation de son enregistrement source OpenAlex retenu par la consolidation. La phase `publications` la remplit.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "49a8d5ba9cee"
down_revision: str | Sequence[str] | None = "662b5308f866"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE publications.publications ADD COLUMN impact jsonb,
        ADD CONSTRAINT publications_impact_is_object
            CHECK ((impact IS NULL) OR (jsonb_typeof(impact) = 'object'::text))
    """)
    op.execute("""
        COMMENT ON COLUMN publications.publications.impact IS
        'Indicateurs de citation de l''enregistrement source OpenAlex retenu par la consolidation.'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE publications.publications DROP COLUMN impact")
