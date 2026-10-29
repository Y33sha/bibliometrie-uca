"""Ajoute la valeur 'recorded_talk' à l'enum doc_type

La captation vidéo d'une conférence ou d'un séminaire se distingue de la communication sans enregistrement (`conference`).

Revision ID: c3e9a7f1d204
Revises: b6d1f9a3c8e2
Create Date: 2026-10-29 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3e9a7f1d204"
down_revision: str | Sequence[str] | None = "b6d1f9a3c8e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'recorded_talk' AFTER 'conference'")


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade passe les lignes de ce type
    # à 'other' et laisse la valeur dans le type, inutilisée.
    op.execute("UPDATE publications SET doc_type = 'other' WHERE doc_type = 'recorded_talk'")
    op.execute("UPDATE source_records SET doc_type = 'other' WHERE doc_type = 'recorded_talk'")
