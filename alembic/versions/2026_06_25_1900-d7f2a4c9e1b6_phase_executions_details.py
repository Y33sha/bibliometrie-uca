"""pipeline_phase_executions : colonnes input/output → details

L'observable uniforme entrée/sortie est remplacé par une colonne `details` libre,
propre à chaque phase : volumes avant/après des tables (clé `tables`, posée
automatiquement par le recorder) et indicateurs sur-mesure remontés par la phase
(ex. `by_source` pour les phases multi-sources). Les exécutions déjà capturées
sont des données de test sans valeur ; on ne migre pas le contenu.

Revision ID: d7f2a4c9e1b6
Revises: c4e9a1b7f2d8
Create Date: 2026-06-25 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7f2a4c9e1b6"
down_revision: str | Sequence[str] | None = "c4e9a1b7f2d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pipeline_phase_executions DROP COLUMN input")
    op.execute("ALTER TABLE pipeline_phase_executions DROP COLUMN output")
    op.execute(
        "ALTER TABLE pipeline_phase_executions ADD COLUMN details jsonb NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE pipeline_phase_executions DROP COLUMN details")
    op.execute("ALTER TABLE pipeline_phase_executions ADD COLUMN input jsonb")
    op.execute("ALTER TABLE pipeline_phase_executions ADD COLUMN output jsonb")
