"""Ajoute la clé de config laboratories_display_types

Types de structure affichés sur la page publique des laboratoires. Défaut `["labo"]`
(comportement historique : seuls les laboratoires). Éditable depuis admin/config.

Revision ID: c5e2a71f9b04
Revises: b8d1e4a20f63
Create Date: 2026-07-05 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5e2a71f9b04"
down_revision: str | Sequence[str] | None = "b8d1e4a20f63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO config (key, value, description) VALUES "
        "('laboratories_display_types', '[\"labo\"]', "
        "'Types de structure affichés sur la page publique des laboratoires') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM config WHERE key = 'laboratories_display_types'")
