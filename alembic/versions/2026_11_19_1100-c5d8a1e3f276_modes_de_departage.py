"""Modes de rattachement par départage d'une forme de nom ambiguë

Le type `resolution_mode` gagne une valeur par indice de départage (`domain.persons.tie_break`) : coauteurs, laboratoire, structure HAL, revue, années d'activité.

Revision ID: c5d8a1e3f276
Revises: a8c4e2f7b913
Create Date: 2026-11-19 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5d8a1e3f276"
down_revision: str | Sequence[str] | None = "a8c4e2f7b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODES = ("coauthors", "laboratory", "hal_structure", "serial", "activity_years")


def upgrade() -> None:
    for mode in _MODES:
        op.execute(f"ALTER TYPE resolution_mode ADD VALUE IF NOT EXISTS '{mode}'")


def downgrade() -> None:
    # PostgreSQL ne retire pas une valeur d'enum : les contributions rattachées par départage perdent leur personne, les valeurs restent dans `resolution_mode`.
    modes = ", ".join(f"'{mode}'" for mode in _MODES)
    op.execute(f"""
        UPDATE publications.contributions SET person_id = NULL, resolution_mode = NULL
        WHERE resolution_mode::text IN ({modes})
    """)
