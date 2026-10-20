"""Phases harvest et harvest_by_person dans l'historique des exécutions

Revision ID: 3c9a7e5d1f20
Revises: 8d4f1a2b6c3e
Create Date: 2026-10-20 12:00:00.000000

`ops.pipeline_phase_executions.phase` nomme les phases de collecte `harvest` et `harvest_by_person`. Le moissonnage quotidien de HAL se cale sur la dernière exécution `harvest` réussie.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3c9a7e5d1f20"
down_revision: str | Sequence[str] | None = "8d4f1a2b6c3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RENAMES = (("extract", "harvest"), ("extract_by_person", "harvest_by_person"))


def upgrade() -> None:
    for old, new in _RENAMES:
        op.execute(
            f"UPDATE ops.pipeline_phase_executions SET phase = '{new}' WHERE phase = '{old}'"
        )


def downgrade() -> None:
    for old, new in _RENAMES:
        op.execute(
            f"UPDATE ops.pipeline_phase_executions SET phase = '{old}' WHERE phase = '{new}'"
        )
