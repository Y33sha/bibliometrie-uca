"""Mode d'entrée `fetch_missing_theses` dans `staging`

Une ligne de `staging` peut entrer par la recherche dans theses.fr du NNT d'une thèse trouvée dans une autre source.

Revision ID: 3e7a9c2d5b18
Revises: 8b3f1c2e9d54
Create Date: 2026-10-17 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3e7a9c2d5b18"
down_revision: str | Sequence[str] | None = "8b3f1c2e9d54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "'bulk'::text, 'fetch_missing_doi'::text, 'fetch_missing_hal'::text,"
    " 'manual_export'::text, 'person_identifier'::text"
)


def upgrade() -> None:
    op.execute("ALTER TABLE sources.staging DROP CONSTRAINT staging_entry_mode_check")
    op.execute(f"""
        ALTER TABLE sources.staging ADD CONSTRAINT staging_entry_mode_check
            CHECK (entry_mode = ANY (ARRAY[{_BEFORE}, 'fetch_missing_theses'::text]))
    """)


def downgrade() -> None:
    op.execute("DELETE FROM sources.staging WHERE entry_mode = 'fetch_missing_theses'")
    op.execute("ALTER TABLE sources.staging DROP CONSTRAINT staging_entry_mode_check")
    op.execute(f"""
        ALTER TABLE sources.staging ADD CONSTRAINT staging_entry_mode_check
            CHECK (entry_mode = ANY (ARRAY[{_BEFORE}]))
    """)
