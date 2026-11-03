"""Ajoute la valeur 'journal_issue' à l'enum doc_type

Le numéro de revue, dirigé ou non, est exclu des publications. Ses articles sont des publications.

Revision ID: f3b8d1a6c925
Revises: e5a2c9d71f38
Create Date: 2026-11-03 21:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3b8d1a6c925"
down_revision: str | Sequence[str] | None = "e5a2c9d71f38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'journal_issue' AFTER 'proceedings'")


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade passe les lignes de ce type à 'other' et laisse la valeur dans le type, inutilisée.
    op.execute(
        "UPDATE publications.publications SET doc_type = 'other' WHERE doc_type = 'journal_issue'"
    )
    op.execute(
        "UPDATE sources.source_records SET doc_type = 'other' WHERE doc_type = 'journal_issue'"
    )
