"""Teinte de l'interface

`brand_hue` contient la teinte de l'interface : angle OKLCH en degrés, entier de 0 à 359.

Revision ID: c4e8a1f7d236
Revises: b8f2d6e1c947
Create Date: 2026-10-28 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e8a1f7d236"
down_revision: str | Sequence[str] | None = "b8f2d6e1c947"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO ops.config (key, value, description) VALUES "
        "('brand_hue', '196', "
        "'Teinte de l''interface : angle OKLCH en degrés, de 0 à 359.') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "ALTER TABLE ops.config ADD CONSTRAINT config_brand_hue_is_angle CHECK ("
        "  key <> 'brand_hue' OR (jsonb_typeof(value) = 'number'"
        "  AND (value)::numeric BETWEEN 0 AND 359"
        "  AND (value)::numeric = trunc((value)::numeric)))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_brand_hue_is_angle")
    op.execute("DELETE FROM ops.config WHERE key = 'brand_hue'")
