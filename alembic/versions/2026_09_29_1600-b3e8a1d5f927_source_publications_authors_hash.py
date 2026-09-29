"""source_publications : empreinte de la partie auteurs du payload source

`authors_hash` porte l'empreinte de la partie auteurs du payload source à la dernière synchronisation des signatures. Une notice dont l'empreinte est inchangée garde ses signatures en l'état, sans construction ni comparaison.

Revision ID: b3e8a1d5f927
Revises: a7d2f9c4e816
Create Date: 2026-09-29 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3e8a1d5f927"
down_revision: str | Sequence[str] | None = "a7d2f9c4e816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_publications",
        sa.Column(
            "authors_hash",
            sa.Text(),
            nullable=True,
            comment="Empreinte de la partie auteurs du payload source, à la dernière synchronisation des signatures.",
        ),
    )


def downgrade() -> None:
    op.drop_column("source_publications", "authors_hash")
