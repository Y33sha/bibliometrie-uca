"""Clés de périmètre présentes dès les migrations

`perimeter_extraction` et `perimeter_persons` valent `null` tant que le seed d'établissement ne désigne aucun périmètre. Une base existante garde sa valeur.

Revision ID: 5d2b8e4f7a19
Revises: 3f9c2d7a1e84
Create Date: 2026-11-02 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5d2b8e4f7a19"
down_revision: str | Sequence[str] | None = "3f9c2d7a1e84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO ops.config (key, value, description) VALUES "
        "('perimeter_extraction', 'null', "
        "'Périmètre pour déterminer les structures à interroger lors de l''extraction'), "
        "('perimeter_persons', 'null', 'Périmètre pour la création des personnes') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ops.config WHERE key IN ('perimeter_extraction', 'perimeter_persons') "
        "AND jsonb_typeof(value) = 'null'"
    )
