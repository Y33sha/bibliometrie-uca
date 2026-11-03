"""Identifiant de la file de normalisation de staging sans séquence

`id` désigne une ligne de `staging`, comme l'identifiant des autres files. La création de la file lui a donné une séquence et une valeur par défaut : la migration les retire.

Revision ID: d82f5b1c4e07
Revises: c41e8a7d93b2
Create Date: 2026-11-03 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d82f5b1c4e07"
down_revision: str | Sequence[str] | None = "c41e8a7d93b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE queues.staging_normalization_queue ALTER COLUMN id DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS queues.staging_normalization_queue_id_seq")


def downgrade() -> None:
    pass
