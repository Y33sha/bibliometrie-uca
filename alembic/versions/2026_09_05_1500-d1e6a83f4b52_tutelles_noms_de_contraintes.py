"""Aligne les noms des contraintes NOT NULL de `structure_tutelles` sur celui de la table

PostgreSQL catalogue les contraintes `NOT NULL` et leur donne un nom dérivé de la table. Le renommage de la table ne les suit pas : elles portaient encore celui d'avant, que le snapshot du schéma donnait à lire.

Revision ID: d1e6a83f4b52
Revises: c9d2f5b81a37
Create Date: 2026-09-05 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d1e6a83f4b52"
down_revision: str | Sequence[str] | None = "c9d2f5b81a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLONNES = ("id", "parent_id", "child_id")


def upgrade() -> None:
    for colonne in _COLONNES:
        op.execute(
            f"ALTER TABLE structure_tutelles RENAME CONSTRAINT "
            f"structure_relations_{colonne}_not_null TO structure_tutelles_{colonne}_not_null"
        )


def downgrade() -> None:
    for colonne in _COLONNES:
        op.execute(
            f"ALTER TABLE structure_tutelles RENAME CONSTRAINT "
            f"structure_tutelles_{colonne}_not_null TO structure_relations_{colonne}_not_null"
        )
