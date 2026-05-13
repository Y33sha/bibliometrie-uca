"""add person_name_forms.persons jsonb column

Phase 1 du chantier `DATA_person-name-forms-normalisation.md` : préparer
le remplacement des deux arrays parallèles `person_ids[]` + `sources[]`
par une seule colonne JSONB `persons` au format
``{ "<person_id>": ["<source1>", ...], ... }`` qui couple par
construction chaque `person_id` à ses sources observées.

Colonne nullable à ce stade : la Phase 2 (backfill par oneshots
additifs) la peuplera ; la migration finale (Phase 6) ajoutera la
contrainte NOT NULL + check + index GIN et droppera `person_ids` et
`sources`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-13 15:44:35.951151
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "person_name_forms",
        sa.Column("persons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("person_name_forms", "persons")
