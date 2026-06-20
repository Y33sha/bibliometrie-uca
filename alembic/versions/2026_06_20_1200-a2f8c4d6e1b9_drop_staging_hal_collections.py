"""staging : suppression de la colonne hal_collections

La colonne `staging.hal_collections` (collections HAL par ligne) était redondante :
le normalizer HAL unionne `collCode_s` du `raw_data` aux collections du staging, or
ces dernières en sont un sous-ensemble — elles ne contribuaient donc rien à
`source_publications.hal_collections`, seule forme consommée en aval (facettes,
problèmes HAL, listes/détail). La colonne est dérivable du `raw_data`, on la retire.

Revision ID: a2f8c4d6e1b9
Revises: b7e3f9a1c4d8
Create Date: 2026-06-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a2f8c4d6e1b9"
down_revision: str | Sequence[str] | None = "b7e3f9a1c4d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("staging", "hal_collections")


def downgrade() -> None:
    op.add_column(
        "staging",
        sa.Column("hal_collections", postgresql.ARRAY(sa.Text()), nullable=True),
    )
