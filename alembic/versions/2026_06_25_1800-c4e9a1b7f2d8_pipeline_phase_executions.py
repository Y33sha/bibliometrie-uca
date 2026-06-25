"""pipeline_phase_executions : observabilité par exécution de phase

Remplace le snapshot par run (`pipeline_run_snapshots`) par un enregistrement par
exécution de phase : phase, `run_id`, fenêtre temporelle, statut, signaux,
métriques et observables d'entrée/sortie. `run_id` (séquence générée au
lancement) regroupe les phases d'une même invocation ; tout ce qui est « par
run » se dérive par agrégation, sans table parente.

Cette migration n'ajoute que la nouvelle table. La table `pipeline_run_snapshots`
et le code de l'ancien système sont retirés en fin de chantier, une fois la
lecture migrée — les laisser en place garde la page admin fonctionnelle entre
les deux.

Revision ID: c4e9a1b7f2d8
Revises: f2d9b6a4c1e8
Create Date: 2026-06-25 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e9a1b7f2d8"
down_revision: str | Sequence[str] | None = "f2d9b6a4c1e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE pipeline_run_id_seq AS bigint START WITH 1 INCREMENT BY 1")
    op.execute(
        """
        CREATE TABLE pipeline_phase_executions (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id      bigint NOT NULL,
            phase       text NOT NULL,
            started_at  timestamptz NOT NULL,
            ended_at    timestamptz NOT NULL,
            mode        text NOT NULL,
            sources     text[] NOT NULL DEFAULT '{}',
            status      text NOT NULL CHECK (status IN ('ok', 'warning', 'error')),
            signals     jsonb NOT NULL DEFAULT '[]',
            metrics     jsonb NOT NULL DEFAULT '{}',
            input       jsonb,
            output      jsonb
        )
        """
    )
    op.execute("CREATE INDEX idx_phase_exec_phase ON pipeline_phase_executions (phase)")
    op.execute("CREATE INDEX idx_phase_exec_run_id ON pipeline_phase_executions (run_id)")
    op.execute(
        "CREATE INDEX idx_phase_exec_started_at ON pipeline_phase_executions (started_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE pipeline_phase_executions")
    op.execute("DROP SEQUENCE pipeline_run_id_seq")
