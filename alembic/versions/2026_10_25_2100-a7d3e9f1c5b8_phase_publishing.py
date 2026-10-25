"""Phase publishers_journals renommée publishing

Revision ID: a7d3e9f1c5b8
Revises: e4f1b7c9a2d6
Create Date: 2026-10-25 21:00:00.000000

L'historique des exécutions de phase prend le nom de la phase.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7d3e9f1c5b8"
down_revision: str | Sequence[str] | None = "e4f1b7c9a2d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE ops.pipeline_phase_executions SET phase = 'publishing' "
        "WHERE phase = 'publishers_journals'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ops.pipeline_phase_executions SET phase = 'publishers_journals' "
        "WHERE phase = 'publishing'"
    )
