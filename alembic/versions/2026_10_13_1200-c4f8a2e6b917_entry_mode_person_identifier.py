"""Mode d'entrée `person_identifier` dans `staging`

Une ligne de `staging` peut entrer par l'interrogation d'une source sur l'identifiant d'une personne.

Revision ID: c4f8a2e6b917
Revises: b2e4f6a8d153
Create Date: 2026-10-13 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4f8a2e6b917"
down_revision: str | Sequence[str] | None = "b2e4f6a8d153"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sources.staging DROP CONSTRAINT staging_entry_mode_check")
    op.execute("""
        ALTER TABLE sources.staging ADD CONSTRAINT staging_entry_mode_check
            CHECK (entry_mode = ANY (ARRAY['bulk'::text, 'fetch_missing_doi'::text, 'fetch_missing_hal'::text, 'manual_export'::text, 'person_identifier'::text]))
    """)


def downgrade() -> None:
    op.execute("DELETE FROM sources.staging WHERE entry_mode = 'person_identifier'")
    op.execute("ALTER TABLE sources.staging DROP CONSTRAINT staging_entry_mode_check")
    op.execute("""
        ALTER TABLE sources.staging ADD CONSTRAINT staging_entry_mode_check
            CHECK (entry_mode = ANY (ARRAY['bulk'::text, 'fetch_missing_doi'::text, 'fetch_missing_hal'::text, 'manual_export'::text]))
    """)
