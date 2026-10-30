"""Types de structure traités comme laboratoires

La clé `laboratories_display_types` devient `laboratory_types`. Ses types définissent les laboratoires dans toute l'application.

Revision ID: 3f8a1c6d2e47
Revises: b9d4f2a6e815
Create Date: 2026-10-30 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3f8a1c6d2e47"
down_revision: str | Sequence[str] | None = "b9d4f2a6e815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE ops.config
        SET key = 'laboratory_types',
            description = 'Types de structure traités comme laboratoires.'
        WHERE key = 'laboratories_display_types'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE ops.config
        SET key = 'laboratories_display_types',
            description = 'Types de structure affichés sur la page publique des laboratoires'
        WHERE key = 'laboratory_types'
    """)
