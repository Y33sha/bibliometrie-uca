"""Ajoute la valeur 'physical_object' à l'enum doc_type

Un échantillon ou un instrument identifié par un DOI DataCite (IGSN des échantillothèques) n'est pas un texte publié. Son type le tient hors des publications.

Revision ID: d8b2f6a1c093
Revises: c7a4e1d9f352
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d8b2f6a1c093"
down_revision: str | Sequence[str] | None = "c7a4e1d9f352"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'physical_object'")


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade ramène les lignes qui la
    # portent à 'other' et laisse la valeur dans le type, inutilisée.
    op.execute("UPDATE publications SET doc_type = 'other' WHERE doc_type = 'physical_object'")
    op.execute("UPDATE source_records SET doc_type = 'other' WHERE doc_type = 'physical_object'")
