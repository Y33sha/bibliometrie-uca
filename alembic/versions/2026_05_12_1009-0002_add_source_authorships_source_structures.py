"""add source_authorships.source_structures column

Phase 1 du chantier `DATA_simplify-source-tables.md` : préparer la
suppression de la table `source_structures` en migrant l'information
de traçabilité (les IDs internes des structures côté source) sur
`source_authorships.source_structures` (ARRAY[TEXT]).

La colonne `source_authorships.countries` (ARRAY[TEXT]) existe déjà
depuis le baseline, donc rien à ajouter de ce côté — seul le pipeline
HAL devra commencer à l'écrire (Phase 3 du chantier).

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-12 10:09:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_authorships",
        sa.Column("source_structures", sa.ARRAY(sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_authorships", "source_structures")
