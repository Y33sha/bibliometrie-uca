"""Index des groupes du périmètre sans personne

Revision ID: 9b5e3c1d7a42
Revises: 7d4a2b9e6f13
Create Date: 2026-10-24 16:00:00.000000

La file des orphelins de l'administration lit les groupes du périmètre sans personne.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9b5e3c1d7a42"
down_revision: str | Sequence[str] | None = "7d4a2b9e6f13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX source_contribution_groups_orphans_idx
            ON publications.source_contribution_groups (publication_id)
            WHERE person_id IS NULL AND in_perimeter
    """)


def downgrade() -> None:
    op.execute("DROP INDEX publications.source_contribution_groups_orphans_idx")
