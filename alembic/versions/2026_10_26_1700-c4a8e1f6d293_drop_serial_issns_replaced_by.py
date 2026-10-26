"""Suppression de serial_issns.replaced_by

Revision ID: c4a8e1f6d293
Revises: b7e4d2a9c815
Create Date: 2026-10-26 17:00:00.000000

Aucune règle ni aucun écran ne lit l'ISSN successeur. La forme corrigée d'une valeur mal formée reste un ISSN actif de la même publication en série.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4a8e1f6d293"
down_revision: str | Sequence[str] | None = "b7e4d2a9c815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE publishing.serial_issns DROP COLUMN replaced_by")


def downgrade() -> None:
    op.execute("ALTER TABLE publishing.serial_issns ADD COLUMN replaced_by text")
    op.execute(
        "COMMENT ON COLUMN publishing.serial_issns.replaced_by IS "
        "'ISSN successeur : titre suivant, forme corrigée d''une valeur mal formée.'"
    )
