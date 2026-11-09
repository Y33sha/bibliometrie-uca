"""File de consolidation des publications

La file `queues.publications_queue` contient les publications dont les métadonnées consolidées sont à recalculer, sur le modèle des autres files. L'étape des pays y met les publications dont un enregistrement source change de pays. La tâche `publications.consolidate` la vide.

Revision ID: 83e1e5a8e25f
Revises: b6d1e4a8c372
Create Date: 2026-11-09 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "83e1e5a8e25f"
down_revision: str | Sequence[str] | None = "b6d1e4a8c372"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publications_queue",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("seq", sa.BigInteger, sa.Identity(always=True), nullable=False),
        schema="queues",
    )


def downgrade() -> None:
    op.drop_table("publications_queue", schema="queues")
