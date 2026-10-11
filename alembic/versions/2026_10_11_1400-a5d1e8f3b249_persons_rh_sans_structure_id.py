"""La fiche RH n'a pas de structure

`persons_rh.structure_id` n'est ni écrite ni lue : la colonne et sa clé étrangère disparaissent.

Revision ID: a5d1e8f3b249
Revises: f4c9d6e2a137
Create Date: 2026-10-11 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a5d1e8f3b249"
down_revision: str | Sequence[str] | None = "f4c9d6e2a137"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE persons_rh DROP COLUMN structure_id")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE persons_rh ADD COLUMN structure_id integer
            REFERENCES structures(id)
    """)
