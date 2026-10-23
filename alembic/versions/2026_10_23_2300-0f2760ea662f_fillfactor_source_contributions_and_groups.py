"""fillfactor 90 sur source_contributions et source_contribution_groups

Revision ID: 0f2760ea662f
Revises: 579f75a9a1f6
Create Date: 2026-10-23 23:00:00.000000

Chaque page garde 10 % de place libre : une mise à jour qui ne touche aucune colonne indexée y écrit sa nouvelle version sans écrire dans les index (mise à jour HOT). Le réglage s'applique aux pages écrites ensuite. `VACUUM FULL` l'étend aux pages existantes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0f2760ea662f"
down_revision: str | Sequence[str] | None = "579f75a9a1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("sources.source_contributions", "publications.source_contribution_groups")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} SET (fillfactor = 90)")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} RESET (fillfactor)")
