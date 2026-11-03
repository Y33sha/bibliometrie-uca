"""Ajoute la valeur 'conference_abstract' à l'enum doc_type

Le résumé de conférence publié, en revue ou en recueil, se distingue de la communication sans texte publié (`conference`).

Revision ID: e5a2c9d71f38
Revises: d82f5b1c4e07
Create Date: 2026-11-03 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5a2c9d71f38"
down_revision: str | Sequence[str] | None = "d82f5b1c4e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'conference_abstract' AFTER 'conference'"
    )


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade passe les lignes de ce type à 'conference' et laisse la valeur dans le type, inutilisée.
    op.execute(
        "UPDATE publications SET doc_type = 'conference' WHERE doc_type = 'conference_abstract'"
    )
    op.execute(
        "UPDATE source_records SET doc_type = 'conference' WHERE doc_type = 'conference_abstract'"
    )
