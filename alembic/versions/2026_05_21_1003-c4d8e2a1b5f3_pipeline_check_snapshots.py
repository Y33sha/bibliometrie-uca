"""pipeline_check_snapshots : snapshots des observables post-pipeline

Volet A du chantier `CODE_observabilite-robustesse-pipeline.md`. Table dédiée aux résultats de `run_checks(conn, mode)` exécuté en fin de pipeline (uniquement pour les runs complets, pas `--only`/`--from`). La comparaison delta vs précédent se fait sur le dernier snapshot du même `mode` (daily/weekly/full).

Revision ID: c4d8e2a1b5f3
Revises: f177a34202c2
Create Date: 2026-05-21 10:03:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4d8e2a1b5f3"
down_revision: str | Sequence[str] | None = "f177a34202c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE pipeline_check_snapshots (
            id serial PRIMARY KEY,
            ran_at timestamptz NOT NULL DEFAULT now(),
            mode text NOT NULL,
            payload jsonb NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_pipeline_check_snapshots_mode_ran_at
            ON pipeline_check_snapshots (mode, ran_at DESC)
        """
    )


def downgrade() -> None:
    op.drop_index(
        "idx_pipeline_check_snapshots_mode_ran_at",
        table_name="pipeline_check_snapshots",
    )
    op.drop_table("pipeline_check_snapshots")
