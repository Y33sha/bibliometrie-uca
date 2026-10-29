"""Définition du statut `unverified` dans le commentaire de `serial_issns.status`

Revision ID: c4e8a2f6b1d3
Revises: f3a8c2d6e1b9
Create Date: 2026-10-29 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e8a2f6b1d3"
down_revision: str | Sequence[str] | None = "f3a8c2d6e1b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        COMMENT ON COLUMN publishing.serial_issns.status IS
            'active ; malformed (forme ou clé de contrôle fausse) ; cancelled ; related_title (titre précédent ou suivant) ; supplement ; unverified (ISSN des enregistrements sources, sans notice Sudoc).';
    """)


def downgrade() -> None:
    op.execute("""
        COMMENT ON COLUMN publishing.serial_issns.status IS
            'active ; malformed (forme ou clé de contrôle fausse) ; cancelled ; related_title (titre précédent ou suivant) ; supplement ; unverified (valeur mise de côté, motif inconnu).';
    """)
