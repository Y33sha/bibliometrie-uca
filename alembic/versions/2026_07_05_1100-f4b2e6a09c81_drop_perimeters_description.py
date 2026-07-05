"""Supprime la colonne perimeters.description

La description libre d'un périmètre n'apporte rien : un périmètre est décrit par son
nom, son code et sa liste de structures racines. Colonne retirée du modèle et de l'UI.

Revision ID: f4b2e6a09c81
Revises: d3f8a1c05e47
Create Date: 2026-07-05 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b2e6a09c81"
down_revision: str | Sequence[str] | None = "d3f8a1c05e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE perimeters DROP COLUMN description")


def downgrade() -> None:
    op.execute("ALTER TABLE perimeters ADD COLUMN description text")
