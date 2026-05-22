"""publication_subjects : ajout colonne rejected (bool, default false)

Permet de rejeter manuellement un lien publi↔sujet depuis l'UI sans qu'il
soit re-créé à chaque passage de la phase `subjects`. La purge par source
exclut désormais les rows marquées rejected, et les recalculs de
`usage_count` / `subject_cooccurrences` les ignorent (un rejet doit
effectivement retirer le lien de l'analyse).

Le CRUD UI pour positionner `rejected = true` viendra dans un chantier
séparé.

Revision ID: f8e2c4d1a5b9
Revises: e5a3f7b8c2d4
Create Date: 2026-05-22 18:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f8e2c4d1a5b9"
down_revision: str | Sequence[str] | None = "e5a3f7b8c2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE publication_subjects ADD COLUMN rejected boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE publication_subjects DROP COLUMN rejected")
