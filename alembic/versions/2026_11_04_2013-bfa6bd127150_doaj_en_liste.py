"""DOAJ en liste

Revision ID: bfa6bd127150
Revises: 56f3892a5450
Create Date: 2026-11-04 20:13:42.364338

La présence d'une revue dans le DOAJ est son appartenance à la liste `doaj` de `serial_list_entries`. La migration reporte `serials.is_in_doaj` dans cette liste, puis supprime la colonne.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bfa6bd127150"
down_revision: str | Sequence[str] | None = "56f3892a5450"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO publishing.serial_list_entries (serial_id, list_code)
        SELECT id, 'doaj' FROM publishing.serials WHERE is_in_doaj
        ON CONFLICT DO NOTHING;
        ALTER TABLE publishing.serials DROP COLUMN is_in_doaj;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE publishing.serials ADD COLUMN is_in_doaj boolean DEFAULT false;
        UPDATE publishing.serials s SET is_in_doaj = true
        FROM publishing.serial_list_entries e
        WHERE e.serial_id = s.id AND e.list_code = 'doaj';
    """)
