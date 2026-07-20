"""perimeters.structure_ids devient root_structure_ids

La colonne porte les seules structures racines d'un périmètre, dont la clôture récursive est
matérialisée à part dans `perimeter_structures`. Le nom `structure_ids` ne disait pas « racines »,
et le voisinait avec la clôture que `get_perimeter_structure_ids` calcule sous un nom presque
identique. `root_structure_ids` nomme ce que la colonne contient.

Revision ID: a1b2c3d4e5f6
Revises: c4f8b2e17d93
Create Date: 2026-07-20 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "c4f8b2e17d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE perimeters RENAME COLUMN structure_ids TO root_structure_ids")


def downgrade() -> None:
    op.execute("ALTER TABLE perimeters RENAME COLUMN root_structure_ids TO structure_ids")
