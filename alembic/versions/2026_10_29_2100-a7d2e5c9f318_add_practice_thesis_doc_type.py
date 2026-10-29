"""Ajoute la valeur 'practice_thesis' à l'enum doc_type

La thèse d'exercice (médecine, pharmacie, chirurgie dentaire) donne le diplôme d'État de docteur. Elle se distingue du mémoire (`memoir`) et de la thèse de doctorat (`thesis`).

Revision ID: a7d2e5c9f318
Revises: c3e9a7f1d204
Create Date: 2026-10-29 21:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7d2e5c9f318"
down_revision: str | Sequence[str] | None = "c3e9a7f1d204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'practice_thesis' AFTER 'ongoing_thesis'"
    )


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade passe les lignes de ce type
    # à 'memoir' et laisse la valeur dans le type, inutilisée.
    op.execute("UPDATE publications SET doc_type = 'memoir' WHERE doc_type = 'practice_thesis'")
    op.execute("UPDATE source_records SET doc_type = 'memoir' WHERE doc_type = 'practice_thesis'")
