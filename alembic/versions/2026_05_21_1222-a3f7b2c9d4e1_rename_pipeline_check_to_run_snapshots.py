"""rename pipeline_check_snapshots → pipeline_run_snapshots

Phase 2.2 du chantier `CODE_observabilite-robustesse-pipeline.md`. La table
n'accueille plus seulement les observables (checks) mais aussi les
`PhaseMetrics` par phase + métadonnées du run (durée totale, sources, phases
exécutées). Le nom plus large reflète ce contenu.

DDL only : ALTER TABLE / ALTER INDEX. Aucun changement de schéma du payload
JSONB lui-même — l'enrichissement vit en code (TypedDict `RunSnapshotPayload`).

Revision ID: a3f7b2c9d4e1
Revises: c4d8e2a1b5f3
Create Date: 2026-05-21 12:22:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3f7b2c9d4e1"
down_revision: str | Sequence[str] | None = "c4d8e2a1b5f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pipeline_check_snapshots RENAME TO pipeline_run_snapshots")
    op.execute(
        "ALTER INDEX idx_pipeline_check_snapshots_mode_ran_at "
        "RENAME TO idx_pipeline_run_snapshots_mode_ran_at"
    )
    op.execute(
        "ALTER SEQUENCE pipeline_check_snapshots_id_seq RENAME TO pipeline_run_snapshots_id_seq"
    )


def downgrade() -> None:
    op.execute(
        "ALTER SEQUENCE pipeline_run_snapshots_id_seq RENAME TO pipeline_check_snapshots_id_seq"
    )
    op.execute(
        "ALTER INDEX idx_pipeline_run_snapshots_mode_ran_at "
        "RENAME TO idx_pipeline_check_snapshots_mode_ran_at"
    )
    op.execute("ALTER TABLE pipeline_run_snapshots RENAME TO pipeline_check_snapshots")
