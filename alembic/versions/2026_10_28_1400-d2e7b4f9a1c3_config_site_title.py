"""Titre de l'application

`site_title` contient le titre de l'application. Pour un texte vide, l'interface compose le titre avec le nom de l'établissement.

Revision ID: d2e7b4f9a1c3
Revises: f4a8c2e6b913
Create Date: 2026-10-28 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2e7b4f9a1c3"
down_revision: str | Sequence[str] | None = "f4a8c2e6b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO ops.config (key, value, description) VALUES "
        "('site_title', '\"\"', "
        "'Titre de l''application. Vide : « Bibliométrie » suivi du nom de l''établissement.') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "ALTER TABLE ops.config ADD CONSTRAINT config_site_title_is_text CHECK ("
        "  key <> 'site_title' OR jsonb_typeof(value) = 'string')"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_site_title_is_text")
    op.execute("DELETE FROM ops.config WHERE key = 'site_title'")
