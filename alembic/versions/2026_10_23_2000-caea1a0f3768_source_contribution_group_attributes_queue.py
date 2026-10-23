"""File d'attente des attributs des groupes de contributions sources : source_contribution_group_attributes_queue

Revision ID: caea1a0f3768
Revises: b88a8cebc8aa
Create Date: 2026-10-23 20:00:00.000000

La file reçoit tous les groupes : le run suivant recompose leurs attributs.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "caea1a0f3768"
down_revision: str | Sequence[str] | None = "b88a8cebc8aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE queues.source_contribution_group_attributes_queue (
            id integer PRIMARY KEY
                REFERENCES publications.source_contribution_groups (id) ON DELETE CASCADE,
            seq bigint GENERATED ALWAYS AS IDENTITY
        );
        INSERT INTO queues.source_contribution_group_attributes_queue (id)
        SELECT id FROM publications.source_contribution_groups;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE queues.source_contribution_group_attributes_queue")
