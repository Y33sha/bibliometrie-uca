"""Phase structure_referentials renommée structures

Revision ID: b2e6d9a4c7f1
Revises: d4b8f2a05c31
Create Date: 2026-11-27 12:00:00.000000

L'historique des exécutions de phase prend le nom de la phase.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2e6d9a4c7f1"
down_revision: str | Sequence[str] | None = "d4b8f2a05c31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE ops.pipeline_phase_executions SET phase = 'structures' "
        "WHERE phase = 'structure_referentials'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ops.pipeline_phase_executions SET phase = 'structure_referentials' "
        "WHERE phase = 'structures'"
    )
