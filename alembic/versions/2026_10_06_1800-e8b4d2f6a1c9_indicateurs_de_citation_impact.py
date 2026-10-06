"""Indicateurs de citation dans `source_publications.impact`

La colonne JSONB `impact` regroupe les indicateurs de citation d'un enregistrement source. Le nombre de citations y est repris sous la clé `cited_by_count`, et la colonne `cited_by_count` disparaît.

Revision ID: e8b4d2f6a1c9
Revises: d5f1a8c3e7b2
Create Date: 2026-10-06 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e8b4d2f6a1c9"
down_revision: str | Sequence[str] | None = "d5f1a8c3e7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE public.source_publications ADD COLUMN impact jsonb,
        ADD CONSTRAINT source_publications_impact_is_object
            CHECK ((impact IS NULL) OR (jsonb_typeof(impact) = 'object'::text))
    """)
    op.execute("""
        UPDATE public.source_publications
        SET impact = jsonb_build_object('cited_by_count', cited_by_count)
        WHERE cited_by_count IS NOT NULL
    """)
    op.execute("ALTER TABLE public.source_publications DROP COLUMN cited_by_count")


def downgrade() -> None:
    op.execute("ALTER TABLE public.source_publications ADD COLUMN cited_by_count integer")
    op.execute("""
        UPDATE public.source_publications
        SET cited_by_count = (impact->>'cited_by_count')::integer
        WHERE impact ? 'cited_by_count'
    """)
    op.execute("ALTER TABLE public.source_publications DROP COLUMN impact")
