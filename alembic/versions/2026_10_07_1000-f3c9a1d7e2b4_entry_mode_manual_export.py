"""Mode d'entrée `manual_export` dans `staging`

Une ligne de `staging` peut entrer par l'import d'un export de l'interface d'une source.

Revision ID: f3c9a1d7e2b4
Revises: e8b4d2f6a1c9
Create Date: 2026-10-07 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3c9a1d7e2b4"
down_revision: str | Sequence[str] | None = "e8b4d2f6a1c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.staging DROP CONSTRAINT staging_entry_mode_check")
    op.execute("""
        ALTER TABLE public.staging ADD CONSTRAINT staging_entry_mode_check
            CHECK (entry_mode = ANY (ARRAY['bulk'::text, 'fetch_missing_doi'::text, 'fetch_missing_hal'::text, 'manual_export'::text]))
    """)


def downgrade() -> None:
    op.execute("DELETE FROM public.staging WHERE entry_mode = 'manual_export'")
    op.execute("ALTER TABLE public.staging DROP CONSTRAINT staging_entry_mode_check")
    op.execute("""
        ALTER TABLE public.staging ADD CONSTRAINT staging_entry_mode_check
            CHECK (entry_mode = ANY (ARRAY['bulk'::text, 'fetch_missing_doi'::text, 'fetch_missing_hal'::text]))
    """)
