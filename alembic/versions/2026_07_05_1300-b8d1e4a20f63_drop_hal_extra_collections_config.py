"""Supprime la clé de config hal_extra_collections

Fonctionnalité jamais utilisée (collections HAL à interroger en plus de celles dérivées
des structures du périmètre). Retirée de l'UI, du pipeline et de la table `config`.

Revision ID: b8d1e4a20f63
Revises: a7c3e9f01b52
Create Date: 2026-07-05 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8d1e4a20f63"
down_revision: str | Sequence[str] | None = "a7c3e9f01b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM config WHERE key = 'hal_extra_collections'")


def downgrade() -> None:
    op.execute(
        "INSERT INTO config (key, value, description) VALUES "
        "('hal_extra_collections', '[]', "
        "'Collections HAL à interroger en plus de celles dérivées des structures du périmètre')"
    )
