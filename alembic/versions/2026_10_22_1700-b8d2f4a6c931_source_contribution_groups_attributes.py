"""Attributs des contributions ajoutés aux groupes : is_corresponding, roles, perimeter_evidence, in_perimeter

Revision ID: b8d2f4a6c931
Revises: e5a7c3d9b214
Create Date: 2026-10-22 17:00:00.000000

La phase contributions les recompose depuis les membres de chaque groupe.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8d2f4a6c931"
down_revision: str | Sequence[str] | None = "e5a7c3d9b214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE publications.source_contribution_groups
            ADD COLUMN is_corresponding boolean,
            ADD COLUMN roles text[],
            ADD COLUMN perimeter_evidence public.perimeter_evidence[] DEFAULT '{}' NOT NULL,
            ADD COLUMN in_perimeter boolean GENERATED ALWAYS AS (cardinality(perimeter_evidence) > 0) STORED NOT NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE publications.source_contribution_groups
            DROP COLUMN in_perimeter,
            DROP COLUMN perimeter_evidence,
            DROP COLUMN roles,
            DROP COLUMN is_corresponding
    """)
