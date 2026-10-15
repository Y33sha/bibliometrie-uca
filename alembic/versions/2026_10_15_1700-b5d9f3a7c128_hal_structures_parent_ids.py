"""Identifiants des parents de chaque structure HAL

`ref.hal_structures.parent_ids` recopie `parentDocid_i`. Les relations (`ref.hal_structure_relations`) se reconstruisent depuis cette colonne, et les parents absents du référentiel se chargent au run suivant. Le remplissage reprend les relations en place.

Revision ID: b5d9f3a7c128
Revises: a3c7e1f9b264
Create Date: 2026-10-15 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b5d9f3a7c128"
down_revision: str | Sequence[str] | None = "a3c7e1f9b264"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ref.hal_structures ADD COLUMN parent_ids integer[] NOT NULL DEFAULT '{}';
        UPDATE ref.hal_structures h
        SET parent_ids = r.parent_ids
        FROM (
            SELECT child_id, array_agg(parent_id ORDER BY parent_id) AS parent_ids
            FROM ref.hal_structure_relations
            GROUP BY child_id
        ) r
        WHERE r.child_id = h.hal_structure_id;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE ref.hal_structures DROP COLUMN parent_ids")
