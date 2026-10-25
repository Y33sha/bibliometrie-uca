"""File des groupes dont la personne est à redécider : group_resolution_queue

Revision ID: 8c3d5f7a1b26
Revises: 4e7b2a9c5d18
Create Date: 2026-10-24 20:00:00.000000

Un groupe dont les membres changent, ou que soutient un identifiant ou une forme de nom invalidé, garde sa personne et entre dans la file : le rattachement des groupes le redécide.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8c3d5f7a1b26"
down_revision: str | Sequence[str] | None = "4e7b2a9c5d18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE queues.group_resolution_queue (
            id integer PRIMARY KEY
                REFERENCES publications.source_contribution_groups (id) ON DELETE CASCADE,
            seq bigint GENERATED ALWAYS AS IDENTITY
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE queues.group_resolution_queue")
