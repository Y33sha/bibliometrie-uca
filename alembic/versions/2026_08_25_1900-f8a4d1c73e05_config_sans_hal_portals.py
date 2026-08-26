"""Supprime la clé de configuration hal_portals

L'extraction HAL par portail n'existe plus : les collections des structures du périmètre
déterminent seules ce qui est moissonné. La ligne subsistait sans lecteur.

Revision ID: f8a4d1c73e05
Revises: e7f3c2a91d64
Create Date: 2026-08-25 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f8a4d1c73e05"
down_revision: str | Sequence[str] | None = "e7f3c2a91d64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM config WHERE key = 'hal_portals'")


def downgrade() -> None:
    """Recrée la ligne sans valeur : aucune lecture n'en dépend."""
    op.execute(
        "INSERT INTO config (key, value, description) "
        "VALUES ('hal_portals', NULL, 'Portails HAL à interroger (en plus des collections labo)') "
        "ON CONFLICT (key) DO NOTHING"
    )
